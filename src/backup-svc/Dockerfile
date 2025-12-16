FROM python:3.9

# Install PostgreSQL client and cron
RUN apt-get update && apt-get install -y postgresql-client cron && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application code and cronfile into the container
COPY backup_upload.py /app
COPY cronfile /etc/cron.d/db-backup-cron

# Install Python dependencies
RUN pip install boto3

# Set permissions for cronfile and give execution permission
RUN chmod 0644 /etc/cron.d/db-backup-cron && crontab /etc/cron.d/db-backup-cron

# Create a log file for cron output
RUN touch /var/log/cron.log

# Run the cron daemon in foreground (for Docker compatibility)
CMD cron -f

