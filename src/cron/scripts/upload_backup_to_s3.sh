#!/bin/bash
# S3 upload script
# Uploads the database backup to S3 bucket

set -e

BACKUP_DATE=$(date +%Y_%m_%d)
BACKUP_FILE="/tmp/pg_backup_${BACKUP_DATE}.sql"
S3_BUCKET="s3://ws-prod-main-db-backups-2025-feb"
S3_FILE="pg_backup_${BACKUP_DATE}.sql"

echo "$(date): Starting S3 upload..."

# Check if backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    echo "Please ensure backup_db.sh ran successfully before this script"
    exit 1
fi

# Check file size
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup file: $BACKUP_FILE"
echo "Backup size: $BACKUP_SIZE"
echo "S3 destination: ${S3_BUCKET}/${S3_FILE}"

# Upload to S3
if aws s3 cp "$BACKUP_FILE" "${S3_BUCKET}/${S3_FILE}"; then
    echo "$(date): Upload to S3 completed successfully!"
else
    echo "ERROR: S3 upload failed"
    exit 1
fi
