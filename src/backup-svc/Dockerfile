FROM python:3.9

# Install PostgreSQL client and cron
RUN apt-get update && apt-get install -y postgresql-client cron && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application code and cronfile
COPY backup.py /app/
COPY cronfile /etc/cron.d/db-backup-cron

# Install Python dependencies
RUN pip install boto3

# Set permissions for cronfile
RUN chmod 0644 /etc/cron.d/db-backup-cron && crontab /etc/cron.d/db-backup-cron

# Create log files (cron wrapper log + application log)
RUN touch /var/log/cron.log /var/log/backup.log && \
    chmod 0666 /var/log/cron.log /var/log/backup.log

# Run the cron daemon in foreground.
# Also tail the log files so that INFO/DEBUG output from the backup script
# (both the rotating file handler and anything redirected by cron) is visible
# via `docker logs <container>`.
CMD ["sh", "-c", "cron -f & exec tail -F /var/log/cron.log /var/log/backup.log"]
