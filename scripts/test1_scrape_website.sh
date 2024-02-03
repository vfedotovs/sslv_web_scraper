#!/bin/bash


### Test_web_scraper module 1 ###
#
#
# - Create uniq folder name YYYY_MM_DD_test1_web_sraper
curr_date=$(date +%Y-%m-%d)
new_curr_date=$(date +%Y-%m-%d_%H%M)
new_folder_name="${new_curr_date}_test1_scrape_website_module"


echo " ---> Creating folder $new_folder_name ... ---"
mkdir $new_folder_name
cd $new_folder_name


# - clone latest repo version
echo " ---> Cloning SSLV scrape project repository from internet ... ---"
git clone https://github.com/vfedotovs/sslv_web_scraper.git .


# echo " ---> Switching to development branch ... ---"
# git checkout development
# git status

echo " ---> Will be runing test for main branch ... ---"

echo " ---> No setup files needed for this module only internet access  ... ---"

# - Copy test file requirements
# echo " ---> Copying setup file-1 Ogre-raw-data-report.txt  ... ---"
# cp ../sslv_testing_files/Ogre-raw-data-report.txt .
# ls -la | grep txt
# cp Ogre-raw-data-report.txt data
# mv data/Ogre-raw-data-report.txt data/Ogre-raw-data-report-${curr_date}.txt
# ls -la data


# Run code pyhton3 ../../web_sraper.py
echo " ---> Running test: python3 for module web_scraper.py ... ---"
python3 src/ws/app/wsmodules/web_scraper.py


# - Test if file is created Ogre-raw-data-report.txt
echo " ---> Checking if output file  exist  ... ---"
find . -name '*.txt'

# out_file_lc=$(cat pandas_df.csv | wc -l)
# echo " ---> pandas_df.csv line count: $out_file_lc"


# if [ "$out_file_lc" -gt 0 ]; then
#   echo "Test result pandas_df.csv line count > 0: Pass";
# else
#    echo "Test result file pandas_df.csv exists:  Fail";
# fi





