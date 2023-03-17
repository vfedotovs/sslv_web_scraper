#!/bin/bash



### Test_web_scraper module df_cleaner.py  ###

# Create folder folder date_test_web_sraper
curr_date=$(date +%Y-%m-%d)
#folder_name="${curr_date}_test2_data_formater_v14_module"
new_curr_date=$(date +%Y-%m-%d_%H%M)
new_folder_name="${new_curr_date}_test3_df_cleaner_module"


echo "[TEST INFO] ---> Creating folder $new_folder_name ... ---"
mkdir $new_folder_name
cd $new_folder_name


# - clone latest repo version
echo " ---> Cloning repository ... ---"
git clone https://github.com/vfedotovs/sslv_web_scraper.git .
ls -la


# - clone latest repo version
echo " ---> Copying setup files ... ---"
cp  ~/projects/sslv_testing_files/Ogre-raw-data-report.txt .  || { echo "---> Error: Setup file Ogre-raw-data-report.txt copy failed"; exit 1; }
cp  ~/projects/sslv_testing_files/pandas_df.csv .  || { echo "---> Error: Setup file pandas_df.csv copy failed"; exit 1; }

mkdir data 
cp ../sslv_testing_files/Ogre-raw-data-report.txt .
cp ../sslv_testing_files/pandas_df.csv .

ls -la | grep txt
ls -la | grep csv

cp Ogre-raw-data-report.txt data
mv data/Ogre-raw-data-report.txt data/Ogre-raw-data-report-${curr_date}.txt
echo " ---> Listing files in data folder ... ---"
ls -la data


# - run code pyhton3 ../../web_sraper.py
echo " ---> Running test: python3 src/ws/wsmodules/df_cleaner.py module ... ---"
python3  src/ws/app/wsmodules/df_cleaner.py


# - test if file is created Ogre-raw-data-report.txt
echo " ---> Checking if output file cleaned-sorted-df.csv exist  ... ---"
out_file_lc=$(cat cleaned-sorted-df.csv | wc -l)
echo " ---> cleaned-sorted-df.csv line count: $out_file_lc"


if [ "$out_file_lc" -gt 0 ]; then
  echo " ---> Test 3 result cleaned-sorted-df.csv line count > 0: Pass";
else
   echo " ---> Test 3 result file cleaned-sorted-df.csv exists:  Fail";
fi





