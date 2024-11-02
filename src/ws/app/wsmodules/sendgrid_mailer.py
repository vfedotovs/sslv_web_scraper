#!/usr/bin/env python3
""" sendgrid_mailer.py module

Main usage case for this module:
    1. Send email using sendmail gateway
    2. Include pdf file as attachment (new feature comparing with Milestone 1)
    3. Add ad oneline information about each apartment in email body
    4. Use environemt varibales for source/destination email and API key
"""
import base64
import os
import os.path
from datetime import datetime
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import sys
from sendgrid.helpers.mail import (Mail,
                                   Attachment,
                                   FileContent,
                                   FileName,
                                   FileType,
                                   Disposition,
                                   ContentId)
from sendgrid import SendGridAPIClient


log = logging.getLogger('sendgrid_mailer')
log.setLevel(logging.INFO)
fa_log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fa_log_format)
log.addHandler(ch)
fh = handlers.RotatingFileHandler('sendgrid_mailer.log',
                                  maxBytes=(1048576*5),
                                  backupCount=7)
fh.setFormatter(fa_log_format)
log.addHandler(fh)


data_files = ['email_body_txt_m4.txt',
              'Mailer_report.txt',
              'Ogre-raw-data-report.txt',
              'cleaned-sorted-df.csv',
              'pandas_df.csv',
              'basic_price_stats.txt',
              'email_body_add_dates_table.txt',
              '1_rooms_tmp.txt',
              '1-4_rooms.png',
              '1_rooms.png',
              '2_rooms.png',
              '3_rooms.png',
              '4_rooms.png',
              'test.png',
              'mrv2.txt',
              'Ogre_city_report.pdf']


def remove_tmp_files(files_to_remove: list) -> None:
    """FIXME: Refactor this function to better code"""
    directory = os.getcwd()
    log.info(f"Attempting clean temp files from {directory} folder")
    for file in files_to_remove:
        try:
            log.info(f"Trying to deleting file: {file} ")
            os.remove(file)
            log.info(f"File: {file} deleted with success ")
        except OSError as e:
            log.error(f" {e.strerror} ")


def gen_debug_subject() -> str:
    """Function generates uniq subject line to improve debugging
    Example of subject:
    Ogre City Apartments for sale from ss.lv webscraper v1.4.8 20221001_1019"""
    log.info("Generating email subject with todays date")
    release = "1.5.8"
    # RELEASE_VERSION = os.environ['RELEASE_VERSION']
    now = datetime.now()
    email_created = now.strftime("%Y%m%d_%H%M")
    city_name = 'Ogre City Apartments for sale from ss.lv web_scraper_v'
    email_subject = city_name + release + "_" + email_created
    subject_ver = email_subject.split('ss.lv')[1]
    log.info(f"Email subject: {subject_ver}")
    return email_subject


def extract_file_contents(file_name: str) -> str:
    """
    Extracts the contents of a file and returns them as a string with two appended new lines.

    This function attempts to read the contents of a specified file. It reads the entire
    file into a list of lines, concatenates them into a single string, and appends two
    new lines (`\n\n`) to the end of the string. If the file is not found, or if any
    other error occurs, an appropriate error message is logged and a fallback string
    indicating that the file was not found is returned.

    Args:
        file_name (str): The path to the file to be read.

    Returns:
        str: The contents of the file as a string, or a fallback message if an error occurs.
    """
    try:
        with open(file_name, 'r', encoding='utf-8') as file_object:
            # Read file in to list
            log.info(f"Trying to read file {file_name} contents.")
            file_content = file_object.readlines()
            # Convert list to string with no space as separator
            extracted_file_contents =  ''.join(file_content)
            extracted_file_contents += "\n\n"
            return extracted_file_contents
    except FileNotFoundError:
        log.error(f"FileNotFoundError: file {file_name} not found.")
        extracted_file_contents = (
            "\n\nFileNotFoundError: " + file_name +
            " Please contact the developer team to provide feedback."
        )
        # Return an empty string or a default value to avoid further errors
        return extracted_file_contents
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")
        extracted_file_contents = (
            "\n\nUnexpected error: file " + file_name +
            " was not found. "
            "Please contact the developer team to provide feedback."
        )
        return extracted_file_contents


def sendgrid_mailer_main() -> None:
    """Main module entry point"""
    log.info(" --- Started sendgrid_mailer module --- ")
    debug_subject = gen_debug_subject()
    mail_body_text = ""

    log.info("Building email body from 4 text files")
    todays_scraped_listed_ads = extract_file_contents('email_body_txt_m4.txt')
    bps_email_content = extract_file_contents('basic_price_stats.txt')
    add_dates_content = extract_file_contents('email_body_add_dates_table.txt')
    scr_rem_content = extract_file_contents('scraped_and_removed.txt')

    final_mail_body = (
            todays_scraped_listed_ads
            + mail_body_text
            + bps_email_content
            + add_dates_content
            + scr_rem_content
    )

    # Creates Mail object instance
    message = Mail(
        from_email=(os.environ.get('SRC_EMAIL')),
        to_emails=(os.environ.get('DEST_EMAIL')),
        subject=debug_subject,
        plain_text_content=final_mail_body)

    log.info("Checking if file Ogre_city_report.pdf exists")
    report_file_exists = os.path.exists('Ogre_city_report.pdf')
    if report_file_exists:
        log.info("Found Ogre_city_report.pdf file")
        file_path = 'Ogre_city_report.pdf'
        with open(file_path, 'rb') as file_object:
            log.info("Reading Ogre_city_report.pdf file as binary")
            data = file_object.read()
            file_object.close()

        # Encodes data with base64 for email attachment
        log.info("Encoding binary data with base64 ")
        encoded_file = base64.b64encode(data).decode()

        # Creates instance of Attachment object
        attached_file = Attachment(
            file_content=FileContent(encoded_file),
            file_type=FileType('application/pdf'),
            file_name=FileName('Ogre_city_report.pdf'),
            disposition=Disposition('attachment'),
            content_id=ContentId('Example Content ID'))

        # Calls attachment method for message instance
        log.info("Attaching encoded data to email object")
        message.attachment = attached_file
        try:
            sendgrid_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            log.info("Trying to send email via Sendgrid API...")
            response = sendgrid_client.send(message)
            log.info(f"Email was sent with with response code: {response.status_code}")
            # Uncoment lines below for debugging
            # log.info(" --- Email response body --- ")
            # log.info(f" {response.body} ")
            # log.info(" --- Email response headers --- ")
            # log.info(f" {response.headers}")
            log.info(" --- End sendgrid_mailer module with success --- ")
        except Exception as e:
            log.error(f"{e.message}")
            log.error(" --- End sendgrid_mailer module with error email was not sent --- ")
    else:
        log.error("FileNotFoundError: Ogre_city_report.pdf was not found ")
        log.error(" --- End sendgrid_mailer module with failure email was not sent --- ")

    remove_tmp_files(data_files)


if __name__ == "__main__":
    sendgrid_mailer_main()
