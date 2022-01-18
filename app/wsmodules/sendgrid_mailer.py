#!/usr/bin/env python3
""" sendgrid_mailer.py module

Main usage case for this module:
    1. Send email using sendmail gateway
    2. Include pdf file as attachment (new feature comparing with Milestone 1)
    3. Add ad oneline information about each apartment in email body 
    4. Use environemt varibales for source/destination email and API key (new feature comparing with release 1.0)
"""
import base64
import os
from sendgrid.helpers.mail import ( Mail, Attachment, FileContent, FileName,
                                    FileType, Disposition, ContentId)
from sendgrid import SendGridAPIClient


def sendgrid_mailer_main() -> None:
    """Main module entry point"""
    print("Debug info: Starting sendgrid mailer module ... ")

    # Read text file for including plain text as email content
    with open('email_body_txt_m4.txt') as f:
        content = f.readlines()
    str_text = '\n'.join([i for i in content[1:]])

    # Creates Mail object instance
    message = Mail(from_email=(os.environ.get('SRC_EMAIL')),
                   to_emails=(os.environ.get('DEST_EMAIL')),
                   subject='Ogre City Apartments for sale from ss.lv webscraper v1.4.2',
                   plain_text_content=str_text)

    try:
        sendgrid_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        response = sendgrid_client.send(message)
        print("Email sent response code:", response.status_code)
    except Exception as e:
        print(e.message)
    print("Debug info: Completed website parsing module ... ")


# Read pdf file file for  attachment
#file_path = 'Ogre_city_report.pdf'
#with open(file_path, 'rb') as f:
#    data = f.read()
#    f.close()

# Encodes binary pdf file data to base64 for email attachment    
#encoded = base64.b64encode(data).decode()


# Creates instance of Attachment object
#attachment = Attachment(file_content = FileContent(encoded),
#                         file_type = FileType('application/pdf'),
#                         file_name = FileName('Ogre_city_report.pdf'),
#                         disposition = Disposition('attachment'),
#                         content_id = ContentId('Example Content ID'))


# Reads Second file for attchment
#with open('report.html', 'rb') as f:
#    html_data = f.read()
#    f.close()
# Encodes binary html file data to base64 for email attachment    
#encoded_file = base64.b64encode(html_data).decode()

# Creates second instance Attachement object
#attachedFile = Attachment(FileContent(encoded_file),
#                          FileName('Report.html'),
#                          FileType('application/html'),
#                          Disposition('attachment'))

# Calls attachment method for message instance 
#message.attachment = attachment  # attaches pdf binary 
#message.attachment = attachedFile  # attached second file Report.html


sendgrid_mailer_main()

