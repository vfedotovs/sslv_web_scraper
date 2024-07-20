#!/usr/bin/env bash

set +x
ws_cont_name=$(docker ps | grep ws | awk '{print $NF}')

mkdir app-logs-and-data
mkdir -p app-logs-and-data/data-files

# Check the exit status of the first command
if [ $? -eq 0 ]; then
    echo "Checking if ws container is running..."
    echo "Current ws container name: $ws_cont_name"
    echo "Collecting ws container log files..."
    docker cp $ws_cont_name:/analytics.log app-logs-and-data
    docker cp $ws_cont_name:/dbworker.log app-logs-and-data
    docker cp $ws_cont_name:/df_changer.log app-logs-and-data
    docker cp $ws_cont_name:/dfcleaner.log app-logs-and-data
    docker cp $ws_cont_name:/file_downloader.log app-logs-and-data
    docker cp $ws_cont_name:/sendgrid_mailer.log app-logs-and-data
    docker cp $ws_cont_name:/ws_main.log app-logs-and-data
    docker cp $ws_cont_name:/web_scraper.log app-logs-and-data
    echo "Collecting backup files from /data folder..."

    docker exec $ws_cont_name bash -c "ls /data/*" | while read line; do docker cp $ws_cont_name:/$line app-logs-and-data/data-files; done
    echo "Collecting bakcup files from /local_lambda_raw_scraped_data... folder..."
    docker exec $ws_cont_name bash -c "ls /local_lambda_raw_scraped_data/*" | while read line; do docker cp $ws_cont_name:/$line app-logs-and-data/data-files; done


        #TODO:  Double check each module required and generated files
    echo "Collecting tmp data files..."
    docker cp $ws_cont_name:/email_body_txt_m4.txt app-logs-and-data/data-files
    docker cp $ws_cont_name:/cleaned-sorted-df.csv app-logs-and-data/data-files
    docker cp $ws_cont_name:/pandas_df.csv app-logs-and-data/data-files
else
    echo "No ws continer running skipping ws container log collection..."
fi


ts_cont_name=$(docker ps | grep ts | awk '{print $NF}')

echo "Collecting task schedule container log ..."
docker cp $ts_cont_name:/app/task_scheduler.log app-logs-and-data

FOLDER_NAME="app-logs-and-data"

# Compress the folder into folder.tgz
tar -czf "${FOLDER_NAME}.tgz" "${FOLDER_NAME}"

# Get the current date and time in the format YYYYMMDD-HHMM
TIMESTAMP=$(date +"%Y%m%d-%H%M")

# Rename folder.tgz to folder-YYYYMMDD-HHMM.tgz
mv "${FOLDER_NAME}.tgz" "${FOLDER_NAME}-${TIMESTAMP}.tgz"

