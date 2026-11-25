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
# Hard floor for a compressed backup: below it the dump is truncated or
# failed. It cannot also catch an empty DB: the staging DBs (30-330 rows)
# dump to 2-8 KB, so the old 10 KB default failed every good nightly backup.
# fleet_watchdog.py checks the size against the live row count instead.
MIN_BACKUP_SIZE_KB = int(os.environ.get("MIN_BACKUP_SIZE_KB", "1"))
# Below floor + rows x this the dump is smaller than its rows need. Staging
# measures ~19 B/row gzip'd; an estimate, so a warning in the log, not an alert.
BACKUP_MIN_BYTES_PER_ROW = int(os.environ.get("BACKUP_MIN_BYTES_PER_ROW", "5"))
# removed_ads keeps history, so the total row count only grows; fewer rows
# than this fraction of the previous backup's means the DB lost data.
BACKUP_SHRINK_RATIO = float(os.environ.get("BACKUP_SHRINK_RATIO", "0.5"))
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


def db_config():
    """(host, user, name, password) from the container environment."""
    return (
        os.environ.get('DB_HOST', 'db'),
        os.environ.get('DB_USER', 'new_docker_user'),
        os.environ.get('DB_NAME', 'new_docker_db'),
        os.environ.get('POSTGRES_PASSWORD', os.environ.get('DB_PASSWORD', '')),
    )


def count_db_rows():
    """(listed_ads, removed_ads) row counts just before the dump, or None.

    Stored as S3 metadata so the dump says what it should contain: the
    verification below and fleet_watchdog.py compare it with the previous
    backup and the live DB. Never raises - a missing count only skips those
    checks, it must not cost the backup itself.
    """
    db_host, db_user, db_name, db_password = db_config()
    env_vars = os.environ.copy()
    env_vars['PGPASSWORD'] = db_password
    try:
        result = subprocess.run(
            ["psql", "-h", db_host, "-U", db_user, "-d", db_name, "-t", "-A", "-c",
             "SELECT (SELECT COUNT(*) FROM listed_ads) || '|' ||"
             " (SELECT COUNT(*) FROM removed_ads)"],
            env=env_vars, capture_output=True, text=True, timeout=60,
        )
        listed, _, removed = result.stdout.strip().partition("|")
        if result.returncode == 0:
            return int(listed), int(removed)
        log.warning("Row count failed (exit %s): %s", result.returncode,
                    result.stderr.strip() or "<no stderr>")
    except Exception as e:
        log.warning("Row count failed: %s", e)
    return None


def backup_postgres():
    db_host, db_user, db_name, db_password = db_config()
    city = get_city()

    log.debug("Resolved config: city=%s db_host=%s db_user=%s db_name=%s",
              city, db_host, db_user, db_name)
    # Do not log the password value
    log.debug("DB password present: %s", bool(db_password))

    # An empty password almost always means the cron job is not seeing the
    # container environment (see entrypoint.sh / run-job.sh). pg_dump would
    # fail auth with a bare "exit status 1", so name the real cause here.
    if not db_password:
        raise RuntimeError(
            "POSTGRES_PASSWORD/DB_PASSWORD is empty - the job is not seeing the"
            " container environment. Check that /app/container.env exists and"
            " that cron runs backup.py via /app/run-job.sh."
        )

    # Generate backup filename with current date
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    backup_filename = f"/tmp/pg_backup_{timestamp}.sql"
    gzip_filename = f"{backup_filename}.gz"

    # Run pg_dump
    log.info("Starting pg_dump for %s on %s (city=%s)", db_name, db_host, city)
    if log.isEnabledFor(logging.DEBUG):
        log.debug("pg_dump command would be: pg_dump --clean --if-exists -h %s -U %s -d %s -f %s",
                  db_host, db_user, db_name, backup_filename)

    env_vars = os.environ.copy()
    env_vars['PGPASSWORD'] = db_password
    # Capture stderr rather than using check=True: a bare CalledProcessError
    # only reports "returned non-zero exit status 1" and hides the actual
    # reason (auth failure, DB not ready, missing table, disk full).
    # --clean --if-exists: the dump drops each object before recreating it, so
    # it restores cleanly over existing tables (no CREATE errors, no duplicate
    # rows) as well as into an empty DB or an init.sql-initialised volume.
    result = subprocess.run(
        [
            "pg_dump",
            "--clean", "--if-exists",
            "-h", db_host,
            "-U", db_user,
            "-d", db_name,
            "-f", backup_filename,
        ],
        env=env_vars,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pg_dump failed (exit {result.returncode}) for {db_name}@{db_host}"
            f" as {db_user}: {result.stderr.strip() or '<no stderr>'}"
        )
    log.info("pg_dump completed successfully.")

    # Compress
    log.info("Compressing backup...")
    gzip_result = subprocess.run(
        ["gzip", "-f", backup_filename], capture_output=True, text=True
    )
    if gzip_result.returncode != 0:
        raise RuntimeError(
            f"gzip failed (exit {gzip_result.returncode}) for {backup_filename}:"
            f" {gzip_result.stderr.strip() or '<no stderr>'}"
        )

    log.debug("Compressed file ready: %s", gzip_filename)
    return gzip_filename

def backup_metadata(rows) -> dict:
    """S3 object metadata recording where the dump came from and what it
    holds. env/city catch a dump uploaded into another env's bucket (the
    2026-09-21 incident); the row counts are left out when unknown."""
    metadata = {"env": os.environ.get("ENV", "prod"), "city": get_city()}
    if rows is not None:
        metadata["listed-ads"], metadata["removed-ads"] = str(rows[0]), str(rows[1])
    return metadata


def read_backup_rows(bucket_name: str, key: str):
    """(listed, removed) from a backup's metadata, or None for a backup made
    before row counts were recorded (or unreadable)."""
    try:
        metadata = boto3.client('s3').head_object(
            Bucket=bucket_name, Key=key).get("Metadata", {})
        return int(metadata["listed-ads"]), int(metadata["removed-ads"])
    except Exception:
        return None


def upload_to_s3(file_path, bucket_name, metadata=None) -> str:
    """Upload the backup file to S3 and return the object key."""
    s3_client = boto3.client('s3')

    # Key with date structure
    now = datetime.datetime.now()
    key = f"db-backups/{now.strftime('%Y')}/{now.strftime('%m')}/{now.strftime('%d')}/pg_backup_{now.strftime('%Y%m%d_%H%M%S')}.sql.gz"

    log.info("Uploading backup to s3://%s/%s", bucket_name, key)
    s3_client.upload_file(file_path, bucket_name, key,
                          ExtraArgs={"Metadata": metadata or {}})
    log.info("Uploaded %s to s3://%s/%s", file_path, bucket_name, key)
    return key


def verify_backup_in_s3(bucket_name: str, key: str, rows=None,
                        previous=None) -> list:
    """M6 monitoring Item 4 (in-process check): confirm the uploaded object
    exists in S3 and holds the data. `rows` are the counts taken just before
    the dump; `previous` is (key, rows) of the backup before this one.

    Critical - raises RuntimeError, which the main block turns into an alert
    email + exit 1:
      - the object is missing, or below MIN_BACKUP_SIZE_KB (truncated or
        failed dump);
      - the DB has fewer than BACKUP_SHRINK_RATIO x the rows of the previous
        backup (it lost data; the uploaded dump is of the damaged DB).
    Warnings - returned for the log only, since bytes per row is an estimate:
      - the object is smaller than MIN_BACKUP_SIZE_KB + rows x
        BACKUP_MIN_BYTES_PER_ROW.
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
            f" {size_bytes} bytes (< {MIN_BACKUP_SIZE_KB} KB hard floor) —"
            f" the dump is truncated or failed"
        )

    previous_key, previous_rows = previous or (None, None)
    if rows is not None and previous_rows is not None:
        total, previous_total = sum(rows), sum(previous_rows)
        if previous_total and total < previous_total * BACKUP_SHRINK_RATIO:
            raise RuntimeError(
                f"the DB lost data: it had {total} rows (listed {rows[0]},"
                f" removed {rows[1]}) at dump time vs {previous_total} in the"
                f" previous backup s3://{bucket_name}/{previous_key}. Today's"
                f" dump is stored but is of the damaged DB - restore from the"
                f" previous one before retention prunes it"
            )

    warnings = []
    if rows is not None:
        expected = min_bytes + sum(rows) * BACKUP_MIN_BYTES_PER_ROW
        if size_bytes < expected:
            warnings.append(
                f"s3://{bucket_name}/{key} is {size_bytes} bytes for"
                f" {sum(rows)} rows (expected >= {expected} at"
                f" {BACKUP_MIN_BYTES_PER_ROW} B/row)"
            )
    for warning in warnings:
        log.warning("Backup verification warning: %s", warning)
    log.info("Backup verified in S3: %s bytes (>= %s KB floor), rows=%s",
             size_bytes, MIN_BACKUP_SIZE_KB, rows)
    return warnings


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
        rows = count_db_rows()
        backup_file = backup_postgres()

        step = "s3_upload"
        s3_bucket = get_s3_bucket()
        previous = None
        try:
            newest = find_newest_backup(s3_bucket)
            if newest is not None:
                previous = (newest[0], read_backup_rows(s3_bucket, newest[0]))
        except Exception as e:
            log.warning("Could not read the previous backup for comparison: %s", e)
        key = upload_to_s3(backup_file, s3_bucket, backup_metadata(rows))

        step = "s3_verify"
        verify_backup_in_s3(s3_bucket, key, rows, previous)

        # Cleanup
        os.remove(backup_file)
        log.info("Local backup file cleaned up: %s", backup_file)
        log.info("=== DB backup job completed successfully ===")
    except Exception as e:
        log.exception("Backup job failed at step %s: %s", step, e)
        stored = ("The dump was uploaded but failed verification."
                  if step == "s3_verify" else "No backup was stored for today.")
        send_alert_email(
            f"SSLV BACKUP ALERT: {city} backup FAILED at {step}",
            f"FAILED: {city} — {step} — {e}\n\n{stored}\n"
            f"Check the {city}-backup-1 container: docker logs {city}-backup-1",
        )
        sys.exit(1)


if __name__ == "__main__":
    if "--staleness-check" in sys.argv:
        check_backup_staleness()
    else:
        run_backup()
