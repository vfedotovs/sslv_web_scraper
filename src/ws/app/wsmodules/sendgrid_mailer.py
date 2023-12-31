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
    "%(asctime)s [%(threadName)-12.12s] "
    " [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s")
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
    log.info(f" --- current working dir {directory} --- ")
    for file in files_to_remove:
        try:
            log.info(f"Trying delete file: {file} ")
            os.remove(file)
        except OSError as e:
            print(f'Error: {file} : {e.strerror}')
            log.info(f"Error deleting {file} : {e.strerror} ")


def gen_debug_subject() -> str:
    """Function generates uniq subject line to improve debugging
    Example of subject:
    Ogre City Apartments for sale from ss.lv webscraper v1.4.8 20221001_1019"""
    release = "v1.4.12 "
    now = datetime.now()
    email_created = now.strftime("%Y%m%d_%H%M")
    city_name = 'Ogre City Apartments for sale from ss.lv webscraper'
    return city_name + release + email_created


def sendgrid_mailer_main() -> None:
    """Main module entry point"""
    log.info(" --- Started sendgrid_mailer module --- ")
    log.info(" Trying to open email_body_txt_m4.txt for email body content ")
    with open('email_body_txt_m4.txt') as file_object:
        file_content = file_object.readlines()

    log.info("Creating email body content from email_body_txt_m4.txt file ")
    mail_body_text = ''.join([i for i in file_content[1:]])
    debug_subject = gen_debug_subject()

    with open('basic_price_stats.txt') as file_object:
        mail_body_text += ''.join(file_object.readlines())

    with open('email_body_add_dates_table.txt') as file_object:
        mail_body_text += ''.join(file_object.readlines())

    # Creates Mail object instance
    message = Mail(
        from_email=(os.environ.get('SRC_EMAIL')),
        to_emails=(os.environ.get('DEST_EMAIL')),
        subject=debug_subject,
        plain_text_content=mail_body_text)

    report_file_exists = os.path.exists('Ogre_city_report.pdf')
    log.info("Checking if file Ogre_city_report.pdf"
             " exists and reading as binary ")
    if report_file_exists:
        # Binary read pdf file
        file_path = 'Ogre_city_report.pdf'
        with open(file_path, 'rb') as file_object:
            data = file_object.read()
            file_object.close()

        # Encodes data with base64 for email attachment
        encoded_file = base64.b64encode(data).decode()

        # Creates instance of Attachment object
        log.info("Attaching  encoded Ogre_city_report.pdf to email object")
        attached_file = Attachment(
            file_content=FileContent(encoded_file),
            file_type=FileType('application/pdf'),
            file_name=FileName('Ogre_city_report.pdf'),
            disposition=Disposition('attachment'),
            content_id=ContentId('Example Content ID'))

        # Calls attachment method for message instance
        message.attachment = attached_file

    try:
        log.info("Attempting to send email via Sendgrid API")
        sendgrid_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        response = sendgrid_client.send(message)
        log.info(f"Email sent with response code: {response.status_code}")
        log.info(" --- Email response body --- ")
        # log.info(f" {response.body} ")
        log.info(" --- Email response headers --- ")
        # log.info(f" {response.headers}")
    except Exception as e:
        log.info(f"{e.message}")
        print(e.message)
    remove_tmp_files(data_files)
    log.info(" --- Ended sendgrid_mailer module --- ")


if __name__ == "__main__":
    sendgrid_mailer_main()
