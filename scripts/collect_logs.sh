#!/usr/bin/env bash

set +x
ws_cont_name=$(docker ps | grep ws | awk '{print $NF}')

echo "Current ws container name:"
echo " $ws_cont_name"


# copy log files
echo "Collecting log files ..."
#docker cp 20231105-1937-deploy-ws-1:/analytics.log .
docker cp $ws_cont_name:/analytics.log .
docker cp 20231105-1937-deploy-ws-1:/dbworker.log .
docker cp 20231105-1937-deploy-ws-1:/df_changer.log .
docker cp 20231105-1937-deploy-ws-1:/dfcleaner.log .
docker cp 20231105-1937-deploy-ws-1:/file_downloader.log .
docker cp 20231105-1937-deploy-ws-1:/sendgrid_mailer.log .
docker cp 20231105-1937-deploy-ws-1:/ws_main.log .

# copy data files


# TODO : implement current file collection
#email_body_txt_m4.txt
#cleaned-sorted-df.csv
#pandas_df.csv
