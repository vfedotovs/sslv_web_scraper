import boto3
import subprocess
import datetime
import os
import sys
import logging
from logging.handlers import RotatingFileHandler


def setup_logging():
    """Configure logging to both rotating file and stdout.
    Respects LOG_LEVEL env var (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.
    """
    logger = logging.getLogger(__name__)

    level_str = os.environ.get("LOG_LEVEL", "INFO").upper().strip()
    level = getattr(logging, level_str, logging.INFO)
    logger.setLevel(level)

    # Rotating file handler (1MB x 5 backups) - for persistent logs inside
    # container. Falls back to stdout-only when /var/log is not writable
    # (local dev runs and tests outside the container).
    try:
        log_dir = "/var/log"
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "backup.log")
        file_handler = RotatingFileHandler(
            log_file, maxBytes=1024 * 1024, backupCount=5
        )
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)-5.5s] : %(funcName)s:%(lineno)d: %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except OSError as e:
        print(f"backup.py: file logging disabled ({e}); using stdout only")

    # Stdout handler - important so logs can surface to `docker logs`
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-5.5s] : %(funcName)s:%(lineno)d: %(message)s"
    )
    stdout_handler.setFormatter(stdout_formatter)
    logger.addHandler(stdout_handler)

    # Prevent propagation to root logger (avoid duplicate lines if basicConfig elsewhere)
    logger.propagate = False

    return logger


log = setup_logging()


AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")

# M6 monitoring Item 4 thresholds
# Minimum plausible size for a compressed backup; a near-empty dump means
# pg_dump connected to an empty DB.
MIN_BACKUP_SIZE_KB = int(os.environ.get("MIN_BACKUP_SIZE_KB", "10"))
# Newest backup object older than this means the cron is silently dead
# (daily backup at 02:00 + generous slack).
BACKUP_MAX_AGE_HOURS = int(os.environ.get("BACKUP_MAX_AGE_HOURS", "26"))


def get_city() -> str:
    return os.environ.get('CITY', 'unknown')


def get_s3_bucket() -> str:
    """Resolve the per-city db-backups bucket (explicit S3_BUCKET or convention)."""
    s3_bucket = os.environ.get('S3_BUCKET')
    if not s3_bucket:
        city_slug = get_city().replace('_', '-')
        env = os.environ.get('ENV', 'prod')
        s3_bucket = f"sslv-{env}-{city_slug}-db-backups"
        log.info("S3_BUCKET not set, using convention: %s", s3_bucket)
    return s3_bucket


def send_alert_email(subject: str, body: str) -> bool:
    """Send a short alert email via AWS SES. Never raises.

    Mirrors ws alert_mailer (M6 Item 3): an alert failure must not mask
    the backup error it is reporting. Returns True if SES accepted it.
    """
    sender = os.environ.get("SRC_EMAIL") or "info@propertydata.lv"
    recipient = os.environ.get("DEST_EMAIL") or "info@propertydata.lv"
    try:
        client = boto3.client("ses", region_name=AWS_REGION)
        response = client.send_email(
            Destination={"ToAddresses": [recipient]},
            Message={
                "Body": {"Text": {"Charset": "UTF-8", "Data": body}},
                "Subject": {"Charset": "UTF-8", "Data": subject},
            },
            Source=sender,
        )
        log.info("Alert email sent! Subject: %s MessageId: %s",
                 subject, response["MessageId"])
        return True
    except Exception as e:
        log.error("Failed to send alert email '%s': %s", subject, e)
        return False


def backup_postgres():
    # Get config from environment
    db_host = os.environ.get('DB_HOST', 'db')
    db_user = os.environ.get('DB_USER', 'new_docker_user')
    db_name = os.environ.get('DB_NAME', 'new_docker_db')
    db_password = os.environ.get('POSTGRES_PASSWORD', os.environ.get('DB_PASSWORD', ''))
    city = get_city()

    log.debug("Resolved config: city=%s db_host=%s db_user=%s db_name=%s",
              city, db_host, db_user, db_name)
    # Do not log the password value
    log.debug("DB password present: %s", bool(db_password))

    # Generate backup filename with current date
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    backup_filename = f"/tmp/pg_backup_{timestamp}.sql"
    gzip_filename = f"{backup_filename}.gz"

    # Run pg_dump
    log.info("Starting pg_dump for %s on %s (city=%s)", db_name, db_host, city)
    if log.isEnabledFor(logging.DEBUG):
        log.debug("pg_dump command would be: pg_dump -h %s -U %s -d %s -f %s",
                  db_host, db_user, db_name, backup_filename)

    env_vars = os.environ.copy()
    env_vars['PGPASSWORD'] = db_password
    subprocess.run(
        [
            "pg_dump",
            "-h", db_host,
            "-U", db_user,
            "-d", db_name,
            "-f", backup_filename,
        ],
        env=env_vars,
        check=True,
    )
    log.info("pg_dump completed successfully.")

    # Compress
    log.info("Compressing backup...")
    subprocess.run(["gzip", "-f", backup_filename], check=True)

    log.debug("Compressed file ready: %s", gzip_filename)
    return gzip_filename

def upload_to_s3(file_path, bucket_name) -> str:
    """Upload the backup file to S3 and return the object key."""
    s3_client = boto3.client('s3')

    # Key with date structure
    now = datetime.datetime.now()
    key = f"db-backups/{now.strftime('%Y')}/{now.strftime('%m')}/{now.strftime('%d')}/pg_backup_{now.strftime('%Y%m%d_%H%M%S')}.sql.gz"

    log.info("Uploading backup to s3://%s/%s", bucket_name, key)
    s3_client.upload_file(file_path, bucket_name, key)
    log.info("Uploaded %s to s3://%s/%s", file_path, bucket_name, key)
    return key


def verify_backup_in_s3(bucket_name: str, key: str) -> None:
    """M6 monitoring Item 4 (in-process check): confirm the uploaded object
    actually exists in S3 with a plausible size.

    A missing object or one below MIN_BACKUP_SIZE_KB (near-empty dump =
    pg_dump connected to an empty DB) raises RuntimeError, which the main
    block turns into an alert email + exit 1.
    """
    s3_client = boto3.client('s3')
    log.info("Verifying uploaded backup s3://%s/%s", bucket_name, key)
    try:
        response = s3_client.head_object(Bucket=bucket_name, Key=key)
    except Exception as e:
        raise RuntimeError(
            f"backup verification failed: uploaded object"
            f" s3://{bucket_name}/{key} not found: {e}"
        )
    size_bytes = response.get("ContentLength", 0)
    min_bytes = MIN_BACKUP_SIZE_KB * 1024
    if size_bytes < min_bytes:
        raise RuntimeError(
            f"backup verification failed: s3://{bucket_name}/{key} is only"
            f" {size_bytes} bytes (< {MIN_BACKUP_SIZE_KB} KB minimum) —"
            f" near-empty dump, DB was likely empty"
        )
    log.info("Backup verified in S3: %s bytes (>= %s KB minimum)",
             size_bytes, MIN_BACKUP_SIZE_KB)


def find_newest_backup(bucket_name: str):
    """Return (key, last_modified, size) of the newest object under the
    db-backups/ prefix, or None when the bucket has no backups."""
    s3_client = boto3.client('s3')
    newest = None
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket_name, Prefix="db-backups/"):
        for obj in page.get('Contents', []):
            if newest is None or obj['LastModified'] > newest['LastModified']:
                newest = obj
    if newest is None:
        return None
    return newest['Key'], newest['LastModified'], newest['Size']


def check_backup_staleness() -> None:
    """M6 monitoring Item 4 (staleness check): alert if the newest backup in
    the city's db-backups bucket is older than BACKUP_MAX_AGE_HOURS.

    Runs as a separate cron entry (see cronfile) hours after the backup job,
    so it catches a silently failing backup (swallowed exit code, dead cron
    line, wrong bucket) that the in-process check cannot see.
    Exits 1 when stale/missing/unverifiable so failures are also visible
    in cron.log.
    """
    city = get_city()
    bucket = get_s3_bucket()
    log.info("=== Backup staleness check starting (city=%s bucket=%s max_age=%sh) ===",
             city, bucket, BACKUP_MAX_AGE_HOURS)
    try:
        newest = find_newest_backup(bucket)
    except Exception as e:
        log.error("Staleness check could not list s3://%s: %s", bucket, e)
        send_alert_email(
            f"SSLV BACKUP ALERT: {city} backup staleness check FAILED",
            f"Could not list backups in s3://{bucket} to verify freshness.\n"
            f"Error: {e}\n\n"
            f"Backups may or may not be running — check AWS credentials/"
            f"permissions and the {city}-backup-1 container.",
        )
        sys.exit(1)

    if newest is None:
        log.error("No backups found in s3://%s", bucket)
        send_alert_email(
            f"SSLV BACKUP ALERT: {city} has NO backups in S3",
            f"No objects found under db-backups/ in s3://{bucket}.\n"
            f"The backup job has never succeeded for this bucket.\n"
            f"Check the {city}-backup-1 container: docker logs {city}-backup-1",
        )
        sys.exit(1)

    key, last_modified, size = newest
    age = datetime.datetime.now(datetime.timezone.utc) - last_modified
    age_hours = age.total_seconds() / 3600
    if age_hours > BACKUP_MAX_AGE_HOURS:
        log.error("Newest backup is stale: %s (%.1fh old)", key, age_hours)
        send_alert_email(
            f"SSLV BACKUP ALERT: {city} backup is STALE ({age_hours:.0f}h old)",
            f"Newest backup in s3://{bucket} is older than the"
            f" {BACKUP_MAX_AGE_HOURS}h threshold.\n\n"
            f"Newest object: {key}\n"
            f"Last modified: {last_modified} ({age_hours:.1f}h ago)\n"
            f"Size: {size} bytes\n\n"
            f"The daily backup cron is likely silently dead.\n"
            f"Check the {city}-backup-1 container: docker logs {city}-backup-1",
        )
        sys.exit(1)
    log.info("Newest backup is fresh: %s (%.1fh old, %s bytes)",
             key, age_hours, size)
    log.info("=== Backup staleness check completed successfully ===")


def run_backup() -> None:
    """Full backup job: pg_dump -> gzip -> upload -> verify in S3.

    Any failure sends an SES alert email and exits 1 (M6 Item 4 — the old
    behavior exited 1 silently, which cron swallowed).
    """
    city = get_city()
    log.info("=== DB backup job starting ===")
    step = "pg_dump"
    try:
        backup_file = backup_postgres()

        step = "s3_upload"
        s3_bucket = get_s3_bucket()
        key = upload_to_s3(backup_file, s3_bucket)

        step = "s3_verify"
        verify_backup_in_s3(s3_bucket, key)

        # Cleanup
        os.remove(backup_file)
        log.info("Local backup file cleaned up: %s", backup_file)
        log.info("=== DB backup job completed successfully ===")
    except Exception as e:
        log.exception("Backup job failed at step %s: %s", step, e)
        send_alert_email(
            f"SSLV BACKUP ALERT: {city} backup FAILED at {step}",
            f"FAILED: {city} — {step} — {e}\n\n"
            f"No verified backup was stored for today.\n"
            f"Check the {city}-backup-1 container: docker logs {city}-backup-1",
        )
        sys.exit(1)


if __name__ == "__main__":
    if "--staleness-check" in sys.argv:
        check_backup_staleness()
    else:
        run_backup()
