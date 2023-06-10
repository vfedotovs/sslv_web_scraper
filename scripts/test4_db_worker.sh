#!/bin/bash

### test_web_scraper ###
# - create folder folder date_test_web_sraper
curr_date=$(date +%Y-%m-%d)
folder_name="${curr_date}_test4_db_worker_module"


echo " ---> Creating folder $folder_name ... ---"
mkdir $folder_name
cd $folder_name

# - clone latest repo version
echo " ---> Cloning repository ... ---"
git clone https://github.com/vfedotovs/sslv_web_scraper.git .
ls -la


# - clone latest repo version
echo " ---> Copying setup files ... ---"
cp ../sslv_testing_files/Ogre-raw-data-report.txt .
cp ../sslv_testing_files/pandas_df.csv .
cp ../sslv_testing_files/cleaned-sorted-df.csv .

ls -la | grep txt
ls -la | grep csv

cp Ogre-raw-data-report.txt data
mv data/Ogre-raw-data-report.txt data/Ogre-raw-data-report-${curr_date}.txt
echo " ---> Listing files in data folder ... ---"
ls -la data


# - run code pyhton3 ../../web_sraper.py
echo " ---> Running test: python3 app/wsmodules/db_worker.py module ... ---"
# DB config import change
sed "s/from app.wsmodules.config import config/from config import config/" ./app/wsmodules/db_worker.py
python3  app/wsmodules/db_worker.py


# - test if file is created Ogre-raw-data-report.txt
echo " ---> Checking if output file cleaned-sorted-df.csv exist  ... ---"
out_file_lc=$(cat cleaned-sorted-df.csv | wc -l)
echo " ---> cleaned-sorted-df.csv line count: $out_file_lc"


if [ "$out_file_lc" -gt 0 ]; then
  echo "Test result cleaned-sorted-df.csv line count > 0: Pass";
else
   echo "Test result file cleaned-sorted-df.csv exists:  Fail";
fi





