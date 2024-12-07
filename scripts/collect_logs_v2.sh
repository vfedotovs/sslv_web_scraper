#!/usr/bin/env bash

set -e # Exit on error

## Log start time
start_time=$(date "+%Y-%m-%d %H:%M:%S")
echo "Script started at: $start_time"

# Define container filters
ws_container=$(docker ps --filter "name=ws" --format "{{.Names}}")
ts_container=$(docker ps --filter "name=ts" --format "{{.Names}}")
db_container=$(docker ps --filter "name=db-1" --format "{{.Names}}")

# Check if the containers are running
if [ -z "$ws_container" ]; then
  echo "No ws container running, skipping log collection..."
  exit 0
fi

echo "Containers detected:"
echo "  WS Container: $ws_container"
echo "  TS Container: $ts_container"
echo "  DB Container: $db_container"

# Logs to collect
log_files=(
  "/analytics.log"
  "/dbworker.log"
  "/raw_data_report_formatter.log"
  "/dfcleaner.log"
  "/s3_file_downloader.log"
  "/sendgrid_mailer.log"
  "/ws_main.log"
  "/web_scraper.log"
)

# Copy logs from the WS container
echo "Collecting logs from WS container..."
for log in "${log_files[@]}"; do
  if docker exec "$ws_container" test -f "$log"; then
    docker cp "$ws_container:$log" .
    echo "Collected: $log"
  else
    echo "File not found in container: $log"
  fi
done

# Collect additional data and backup files
data_folders=("/data" "/local_lambda_raw_scraped_data")
for folder in "${data_folders[@]}"; do
  echo "Collecting backup files from $folder ..."
  docker exec "$ws_container" bash -c "ls $folder/*" | while read -r file; do
    docker cp "$ws_container:$file" .
    echo "Collected: $file"
  done
done

# Collect additional files
extra_files=(
  "/email_body_txt_m4.txt"
  "/cleaned-sorted-df.csv"
  "/pandas_df.csv"
  "/scraped_and_removed.txt"
)

for file in "${extra_files[@]}"; do
  if docker exec "$ws_container" test -f "$file"; then
    docker cp "$ws_container:$file" .
    echo "Collected: $file"
  else
    echo "File not found in container: $file"
  fi
done

# Copy the task scheduler log if the TS container exists
if [ -n "$ts_container" ]; then
  echo "Collecting task scheduler log..."
  docker cp "$ts_container:/app/task_scheduler.log" .
fi

# DB backup
if [ -n "$db_container" ]; then
  echo "Creating DB backup..."
  docker exec -t "$db_container" pg_dump -U new_docker_user -d new_docker_db >"pg_backup_$(date +%Y-%m-%dT%H:%M:%S).sql"
fi

# Log completion time
end_time=$(date "+%Y-%m-%d %H:%M:%S")
echo "Script completed at: $end_time"
