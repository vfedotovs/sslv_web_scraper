#!/bin/bash

### test_web_scraper ###
# - create folder folder date_test_web_sraper
curr_date=$(date +%Y-%m-%d)
#folder_name="${curr_date}_test2_data_formater_v14_module"
new_curr_date=$(date +%Y-%m-%d_%H%M)
new_folder_name="${new_curr_date}_test2_data_format_changer"


echo "[TEST INFO] ---> Creating folder $new_folder_name ... ---"
mkdir $new_folder_name
cd $new_folder_name




# - clone latest repo version
echo "[TEST INFO] ---> Cloning repository ... ---"
git clone https://github.com/vfedotovs/sslv_web_scraper.git .


# - Copy test setup file  - step must be done after git clone because you cannot clone to not empty folder
echo "[TEST INFO] ---> Copying setup file-1 Ogre-raw-data-report.txt  ... ---"
cp  ~/projects/sslv_testing_files/Ogre-raw-data-report.txt .  || { echo "---> Error: Setup file Ogre-raw-data-report.txt copy failed"; exit 1; }

pwd
mkdir data
ls -lh 
cp Ogre-raw-data-report.txt data/


# Renaming file with todays date 
pwd
mv data/Ogre-raw-data-report.txt data/Ogre-raw-data-report-${curr_date}.txt
ls -lh data/ 


echo "[TEST INFO] ---> Setup file Ogre-raw-data-report.txt copy successful ... ---"


echo "[TEST INFO] ---> Runnig test 2 for main branch ... ---"
# git checkout development
# git status


# - run code pyhton3 ../../web_sraper.py
echo "[TEST INFO] ---> Running test: python3 app/wsmodules/data_formater_v14.py module ... ---"
python3 src/ws/app/wsmodules/data_format_changer.py


# - test if file is created Ogre-raw-data-report.txt
echo "[TEST INFO] ---> Checking if output file pandas_df.csv exist  ... ---"
out_file_lc=$(cat pandas_df.csv | wc -l)
echo "[TEST INFO] ---> pandas_df.csv line count: $out_file_lc"


if [ "$out_file_lc" -gt 0 ]; then
  echo "[TEST INFO] ---> Test2 result pandas_df.csv line count > 0: Pass";
else
   echo "[TEST ERROR] ---> Test2 result file pandas_df.csv exists:  Fail";
fi



