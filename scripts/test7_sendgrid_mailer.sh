#!/bin/bash

### Test for Sendgrid_mailer_module ###
# - Create folder folder date_test7_sendgrid_mailer
curr_date=$(date +%Y-%m-%d)
folder_name="${curr_date}_test7_sendgrid_mailer_module"


echo " ---> Creating folder $folder_name ... ---"
mkdir $folder_name
cd $folder_name


echo " ---> Cloning repository ... ---"
git clone https://github.com/vfedotovs/sslv_web_scraper.git .
#git switch GH87_ws_container_crashing
git switch GH110_uniq_sendgrid_mailer_subject


echo " ---> Copying test setup files ... ---"
#cp ../sslv_testing_files/pandas_df.csv .
#cp ../sslv_testing_files/cleaned-sorted-df.csv .
#cp ../sslv_testing_files/basic_price_stats.txt .
cp ../sslv_testing_files/Ogre_city_report.pdf .
cp ../sslv_testing_files/Ogre_city_report.pdf app/wsmodules/
cp ../sslv_testing_files/email_body_txt_m4.txt .
cp ../sslv_testing_files/email_body_txt_m4.txt app/wsmodules/


echo " ---> Running test: python3 app/wsmodules/sendgrid_mailer.py module ... ---"
python3  app/wsmodules/sendgrid_mailer.py


echo " ---> Check email manually to see if it arrived and contains pdf attachment  ... ---"






