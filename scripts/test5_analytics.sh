#!/bin/bash


# Create uniq folder name 
curr_date=$(date +%Y-%m-%d)
new_curr_date=$(date +%Y-%m-%d_%H%M)
new_folder_name="${new_curr_date}_test5_analitycs_module"
echo " ---> Creating folder $new_folder_name ... ---"
mkdir $new_folder_name
cd $new_folder_name


# Clone latest repo version
echo " ---> Cloning repository ... ---"
git clone https://github.com/vfedotovs/sslv_web_scraper.git .
git switch development


echo " ---> Copying setup files ... ---"
cp ../sslv_testing_files/Ogre-raw-data-report.txt .
cp ../sslv_testing_files/pandas_df.csv .
cp ../sslv_testing_files/cleaned-sorted-df.csv .
cp Ogre-raw-data-report.txt data
mv data/Ogre-raw-data-report.txt data/Ogre-raw-data-report-${curr_date}.txt


# Run module
echo " ---> Running test: python3 app/wsmodules/analytics.py module ... ---"
python3  app/wsmodules/analytics.py


# Test if output file is created and file is not empty
echo " ---> Checking if output file basic_price_stats.txt exist  ... ---"
out_file_lc=$(cat basic_price_stats.txt| wc -l)
echo " ---> basic_price_stats.txt line count: $out_file_lc"


if [ "$out_file_lc" -gt 0 ]; then
  echo "Test result basic_price_stats.txt line count > 0: Pass";
else
  echo "Test result file basic_price_stats.txt exists:  Fail";
fi





