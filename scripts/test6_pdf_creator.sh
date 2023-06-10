#!/bin/bash

### test_web_scraper ###
# - create folder folder date_test_web_sraper
curr_date=$(date +%Y-%m-%d)
folder_name="${curr_date}_test6_pdf_creator_module"


echo " ---> Creating folder $folder_name ... ---"
mkdir $folder_name
cd $folder_name

# - clone latest repo version
echo " ---> Cloning repository ... ---"
git clone https://github.com/vfedotovs/sslv_web_scraper.git .
# git switch development
git switch GH151-Refactor-pdf_creator.py-to-improve-quality
# - clone latest repo version
echo " ---> Copying setup files ... ---"
cp ../sslv_testing_files/cleaned-sorted-df.csv .
cp ../sslv_testing_files/basic_price_stats.txt .


# - run code pyhton3 ../../web_sraper.py
echo " ---> Running test: python3 app/wsmodules/pdf_creator.py module ... ---"
python3  app/wsmodules/pdf_creator.py


# - test if file is created Ogre-raw-data-report.txt
echo " ---> Checking if output file Ogre_city_report.pdf exists ... ---"
out_file="Ogre_city_report.pdf"

if [ -f "$out_file" ]; then
    echo "$out_file exists, Test result: Pass"
else 
    echo "$out_file does not exist, Test result: Fail"
fi






