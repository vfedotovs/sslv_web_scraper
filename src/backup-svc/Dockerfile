# Python 3.11 on Debian bookworm, as in src/ws and src/ts.
# - python:3.9-slim: boto3 dropped Python 3.9 on 2026-04-29.
# - bookworm, not trixie: Debian's postgresql-client is 15 on bookworm and 17
#   on trixie. pg_dump 17 writes `SET transaction_timeout = 0;`, which the
#   postgres:15 city DBs reject, so restore_db_city.sh (ON_ERROR_STOP) could
#   not load those dumps. Keep the client major equal to src/db/Dockerfile's.
FROM python:3.11-slim-bookworm

ARG PG_CLIENT_MAJOR=15

# Install PostgreSQL client and cron (minimal install)
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
        cron \
    && rm -rf /var/lib/apt/lists/*

# Fail the build if the base image ever brings a different pg_dump major.
RUN pg_dump --version | grep -q "(PostgreSQL) ${PG_CLIENT_MAJOR}\." \
    || { echo "pg_dump is not ${PG_CLIENT_MAJOR}.x: $(pg_dump --version)" >&2; exit 1; }

# Set working directory
WORKDIR /app

# Copy application code, cron wrapper scripts and cronfile
COPY backup.py entrypoint.sh run-job.sh /app/
COPY cronfile /etc/cron.d/db-backup-cron
RUN chmod 0755 /app/entrypoint.sh /app/run-job.sh

# Install Python dependencies (no cache)
RUN pip install --no-cache-dir boto3

# Set permissions for cronfile
RUN chmod 0644 /etc/cron.d/db-backup-cron && crontab /etc/cron.d/db-backup-cron

# Create log files (cron wrapper log + application log)
RUN touch /var/log/cron.log /var/log/backup.log && \
    chmod 0666 /var/log/cron.log /var/log/backup.log

# entrypoint.sh snapshots the container environment for cron (which does not
# inherit it), then runs the cron daemon in the foreground and tails the log
# files so INFO/DEBUG output from the backup script is visible via
# `docker logs <container>`.
CMD ["/app/entrypoint.sh"]
