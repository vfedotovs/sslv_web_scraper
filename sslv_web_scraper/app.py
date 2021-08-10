#!/usr/bin/env python3
"""
This main module of ss.lv web scraper app that calls all submodules
For email report functionality uncoment sendgrid_mailer import and
include it to main()
"""
import web_scraper
import data_formater
import df_cleaner
import analytics
import pdf_creator
import db_worker
# import sendgrid_mailer
import data_file_cleaner


def main():
        web_scraper
        data_formater
        analytics
        pdf_creator
        db_worker
        data_file_cleaner


if __name__ == "__main__":
    main()
