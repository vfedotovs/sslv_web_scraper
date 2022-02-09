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
from sendgrid.helpers.mail import ( Mail, Attachment, FileContent, FileName,
                                    FileType, Disposition, ContentId)
from sendgrid import SendGridAPIClient


data_files = ['email_body_txt_m4.txt',
              'Mailer_report.txt',
              'Ogre-raw-data-report.txt',
              'cleaned-sorted-df.csv',
              'pandas_df.csv',
              'basic_price_stats.txt']


def remove_tmp_files() -> None:
    """FIXME: Refactor this function to better code"""
    for data_file in data_files:
        try:
            os.remove(data_file)
        except OSError as e:
            print(f'Error: {data_file} : {e.strerror}')


def sendgrid_mailer_main() -> None:
    """Main module entry point"""
    print("Debug info: Starting sendgrid mailer module ...")
    with open('email_body_txt_m4.txt') as f:
        file_content = f.readlines()
    email_body_content = ''.join([i for i in file_content[1:]])

    # Creates Mail object instance
    message = Mail(
            from_email=(os.environ.get('SRC_EMAIL')),
            to_emails=(os.environ.get('DEST_EMAIL')),
            subject='Ogre Apartments for sale from ss.lv webscraper v1.4.5',
            plain_text_content=email_body_content)

    # Binary read pdf file 
    file_path = 'Ogre_city_report.pdf'
    with open(file_path, 'rb') as f:
        data = f.read()
        f.close()

    # Encodes data with base64 for email attachment
    encoded_file = base64.b64encode(data).decode()

    # Creates instance of Attachment object
    attached_file = Attachment(file_content = FileContent(encoded_file),
                            file_type = FileType('application/pdf'),
                            file_name = FileName('Ogre_city_report.pdf'),
                            disposition = Disposition('attachment'),
                            content_id = ContentId('Example Content ID'))

    # Calls attachment method for message instance
    message.attachment = attached_file

    try:
        sendgrid_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        response = sendgrid_client.send(message)
        print("Email sent response code:", response.status_code)
    except Exception as e:
        print(e.message)
    print("Debug info: Removing temp files ... ")
    remove_tmp_files()
    print("Debug info: Completed sendgrid mailer module... ")




sendgrid_mailer_main()
