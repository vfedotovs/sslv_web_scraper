FROM python:3.9-slim

# Install PostgreSQL client and cron (minimal install)
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
        cron \
    && rm -rf /var/lib/apt/lists/*

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
