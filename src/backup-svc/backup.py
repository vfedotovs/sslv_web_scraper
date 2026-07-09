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

    # Ensure log directory exists
    log_dir = "/var/log"
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "backup.log")

    # Rotating file handler (1MB x 5 backups) - for persistent logs inside container
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1024 * 1024, backupCount=5
    )
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-5.5s] : %(funcName)s:%(lineno)d: %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

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


def backup_postgres():
    # Get config from environment
    db_host = os.environ.get('DB_HOST', 'db')
    db_user = os.environ.get('DB_USER', 'new_docker_user')
    db_name = os.environ.get('DB_NAME', 'new_docker_db')
    db_password = os.environ.get('POSTGRES_PASSWORD', os.environ.get('DB_PASSWORD', ''))
    city = os.environ.get('CITY', 'unknown')
    env = os.environ.get('ENV', 'prod')
    
    s3_bucket = os.environ.get('S3_BUCKET')
    if not s3_bucket:
        # Fallback to convention if not set
        city_slug = city.replace('_', '-')
        s3_bucket = f"sslv-{env}-{city_slug}-db-backups"
        log.info("S3_BUCKET not set, using convention: %s", s3_bucket)
    else:
        log.debug("Using explicit S3_BUCKET from environment")

    log.debug("Resolved config: city=%s env=%s db_host=%s db_user=%s db_name=%s",
              city, env, db_host, db_user, db_name)
    log.debug("S3 bucket resolved to: %s", s3_bucket)
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

    try:
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
    except subprocess.CalledProcessError as e:
        log.error("pg_dump failed: %s", e)
        sys.exit(1)

    # Compress
    log.info("Compressing backup...")
    subprocess.run(["gzip", "-f", backup_filename], check=True)

    log.debug("Compressed file ready: %s", gzip_filename)
    return gzip_filename

def upload_to_s3(file_path, bucket_name):
    s3_client = boto3.client('s3')

    # Key with date structure
    now = datetime.datetime.now()
    key = f"db-backups/{now.strftime('%Y')}/{now.strftime('%m')}/{now.strftime('%d')}/pg_backup_{now.strftime('%Y%m%d_%H%M%S')}.sql.gz"

    log.info("Uploading backup to s3://%s/%s", bucket_name, key)
    try:
        s3_client.upload_file(file_path, bucket_name, key)
        log.info("Uploaded %s to s3://%s/%s", file_path, bucket_name, key)
    except Exception as e:
        log.error("Failed to upload to S3: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    log.info("=== DB backup job starting ===")
    try:
        backup_file = backup_postgres()

        s3_bucket = os.environ.get('S3_BUCKET')
        if not s3_bucket:
            # Recompute if needed
            city = os.environ.get('CITY', 'unknown')
            env = os.environ.get('ENV', 'prod')
            city_slug = city.replace('_', '-')
            s3_bucket = f"sslv-{env}-{city_slug}-db-backups"

        upload_to_s3(backup_file, s3_bucket)

        # Cleanup
        os.remove(backup_file)
        log.info("Local backup file cleaned up: %s", backup_file)
        log.info("=== DB backup job completed successfully ===")
    except SystemExit:
        # re-raise exits from inside functions
        raise
    except Exception as e:
        log.exception("Unexpected failure during backup job: %s", e)
        sys.exit(1)
