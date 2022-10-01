#!/usr/bin/env python3
""" sendgrid_mailer.py module functinality:
    1. Send email using SendGrid email api
    2. Dependencies:
        2.1 Requires files: email_body_txt_m4.txt, Ogre_city_report.pdf
        2.2 Requires SendGrid account and API_KEY
    3. Reads file email_body_txt_m4.txt and includes in email body
    4. Attaches file Ogre_city_report.pdf as email attachment
"""
import base64
import os
from datetime import datetime
from sendgrid.helpers.mail import ( Mail, Attachment, FileContent, FileName,
                                    FileType, Disposition, ContentId)
from sendgrid import SendGridAPIClient


def gen_debug_subject() -> str:
    """Funcrion generates uniq subject line to improve debugging
    Example of subject: Ogre City Apartments for sale from ss.lv webscraper v1.4.7 20221001_1019"""
    release = "v1.4.7 "
    now = datetime.now()
    email_created = now.strftime("%Y%m%d_%H%M")
    city_name = 'Ogre City Apartments for sale from ss.lv webscraper'
    return city_name + release + email_created


def sendgrid_mailer_main() -> None:
    """Main module entry point"""
    print("Debug info: Starting sendgrid mailer module ... ")

    # Read text file for including plain text as email content
    with open('email_body_txt_m4.txt') as f:
        content = f.readlines()
    email_body_text = '\n'.join([i for i in content[1:]])
    debug_subject = gen_debug_subject()

    # Creates Mail object instance
    message = Mail(from_email=(os.environ.get('SRC_EMAIL')),
                   to_emails=(os.environ.get('DEST_EMAIL')),
                   subject=debug_subject,
                   plain_text_content=email_body_text)

    # Read pdf file file for  attachment
    file_path = 'Ogre_city_report.pdf'
    with open(file_path, 'rb') as f:
        data = f.read()
        f.close()

    # Encodes binary pdf file data to base64 for email attachment
    encoded = base64.b64encode(data).decode()

    # Creates instance of Attachment object
    pdf_attachment = Attachment(file_content = FileContent(encoded),
        file_type = FileType('application/pdf'),
        file_name = FileName('Ogre_city_report.pdf'),
        disposition = Disposition('attachment'),
        content_id = ContentId('Example Content ID'))

    # Calls attachment method for message instance
    message.attachment = pdf_attachment  # attaches pdf binary

    try:
        sendgrid_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        response = sendgrid_client.send(message)
        print("Email sent response code:", response.status_code)
    except Exception as e:
        print(e.message)
    print("Debug info: Completed sendgrid mailer module ... ")


sendgrid_mailer_main()
