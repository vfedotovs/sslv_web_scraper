#!/bin/sh
# Container entrypoint for the per-city DB backup service.
#
# cron builds a nearly empty environment for its jobs (HOME, LOGNAME, PATH,
# SHELL) and does NOT copy the daemon's environment into them. Everything
# docker-compose injects into PID 1 (POSTGRES_PASSWORD, S3_BUCKET, CITY,
# AWS_*, ...) is therefore invisible to /app/backup.py when cron runs it.
#
# Without this snapshot, backup.py falls back to an empty PGPASSWORD and
# pg_dump fails auth instantly - and the SES alert cannot be sent either
# (no AWS credentials), so the failure stays silent.
set -e

ENV_SNAPSHOT=/app/container.env

printenv \
  | grep -E '^(POSTGRES_PASSWORD|DB_PASSWORD|DB_HOST|DB_USER|DB_NAME|S3_BUCKET|CITY|ENV|LOG_LEVEL|AWS_[A-Z_]+|DEST_EMAIL|SRC_EMAIL|MIN_BACKUP_SIZE_KB|BACKUP_MAX_AGE_HOURS)=' \
  | while IFS='=' read -r key value; do
      # Single-quote the value and escape embedded quotes so passwords with
      # shell metacharacters survive being sourced back in.
      printf "export %s='%s'\n" "$key" "$(printf '%s' "$value" | sed "s/'/'\\\\''/g")"
    done > "$ENV_SNAPSHOT"
chmod 0600 "$ENV_SNAPSHOT"

echo "backup-svc: cron env snapshot written to $ENV_SNAPSHOT" \
     "(city=${CITY:-unknown} bucket=${S3_BUCKET:-<convention>}" \
     "db_password_present=$([ -n "${POSTGRES_PASSWORD:-${DB_PASSWORD:-}}" ] && echo yes || echo NO))"

# Run the cron daemon in the background and tail the log files so that
# INFO/DEBUG output from the backup script (rotating file handler + anything
# redirected by cron) is visible via `docker logs <container>`.
cron -f &
exec tail -F /var/log/cron.log /var/log/backup.log
