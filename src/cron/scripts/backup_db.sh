#!/bin/bash
# Database backup script
# Creates a PostgreSQL dump and stores it in /tmp with date in filename

set -e

BACKUP_DATE=$(date +%Y_%m_%d)
BACKUP_FILE="/tmp/pg_backup_${BACKUP_DATE}.sql"
DB_CONTAINER=$(docker ps --filter "name=db-1" --format "{{.Names}}" | head -n 1)

if [ -z "$DB_CONTAINER" ]; then
    echo "ERROR: Database container not found (looking for *db-1)"
    exit 1
fi

echo "$(date): Starting database backup..."
echo "Database container: $DB_CONTAINER"
echo "Backup file: $BACKUP_FILE"

# Perform backup using pg_dump inside the container
docker exec -t "$DB_CONTAINER" pg_dump -U new_docker_user -d new_docker_db > "$BACKUP_FILE"

if [ -f "$BACKUP_FILE" ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "$(date): Backup completed successfully!"
    echo "Backup size: $BACKUP_SIZE"
    echo "Backup location: $BACKUP_FILE"
else
    echo "ERROR: Backup file not created"
    exit 1
fi
