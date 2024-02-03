#!/bin/bash

# Set the backup destination directory
backup_dir="/path/to/backup/directory"

# Set the current date as the backup file name
backup_file="$backup_dir/backup_$(date +%Y-%m-%d).sql"

# Run the pg_dump command to create the backup
docker exec -t <container_name> pg_dump -U <username> -d <database_name> > $backup_file



# usage
# add this script as cronjob 
# crontab -e
# 0 0 * * * /path/to/backup.sh

