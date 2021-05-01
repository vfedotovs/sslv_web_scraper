#!/usr/bin/env python3
"""
app.py  is 1.2.0 release of ss.lv web scraper

New release features:
    - Extract and save raw data as txt file for specific city apartments for sale advert information
    - Extracts 2 new attributes of advert - date inserted advert and view count is 1 (known issue)
    - Clean and save data as python data frame in csv format
    - Calculate basic price statistics and save them to txt file
    - Use pdf_creator to generate chrats from data frame and create report in pdf file format
    - Use Sendgrid API as email sender with capability to attach pdf files
"""
import web_scraper
import data_formater
import df_cleaner
import analytics
import pdf_creator
import sendgrid_mailer
import data_file_cleaner
import time


def main():
    while True:
        web_scraper
        data_formater
        analytics
        pdf_creator
        sendgrid_mailer
        data_file_cleaner
        time.sleep(86400) # Sleep for 1 day


if __name__ == "__main__":
    main()
