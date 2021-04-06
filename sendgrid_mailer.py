#!/usr/bin/env python3
""" sendgrid_mailer.py module

Main usage case for this module:
    1. Send email using sendmail gateway
    2. Include pdf file as attachment (new feature comparing with release 1.0)
    3. Add ad oneline information in email body - not implemented yet
    4. Use environemt varibales for source/destination email and API key (new feature comparing with release 1.0)
"""
import base64
import os


from sendgrid.helpers.mail import (
    Mail, Attachment, FileContent, FileName,
    FileType, Disposition, ContentId)
from sendgrid import SendGridAPIClient

# read file for plain_text
with open('Mailer_report.txt') as f:
    content = f.readlines()
# you may also want to remove whitespace characters like `\n` at the end of each line
#plain_text = [x.strip() for x in content]
str_text = '\n'.join([i for i in content[1:]])



message = Mail(
    from_email=(os.environ.get('SRC_EMAIL')),
    to_emails=(os.environ.get('DEST_EMAIL')),
    subject='Ogre City Apartments for sale from ss.lv webscraper',
    #html_content= '<strong> Email send by sendgrid <strong>')
    plain_text_content=str_text)


# Include pdf file attachment
file_path = 'Ogre_city_report.pdf'
with open(file_path, 'rb') as f:
    data = f.read()
    f.close()
encoded = base64.b64encode(data).decode()
# Creates instance of attachment
attachment = Attachment(file_content = FileContent(encoded),
                         file_type = FileType('application/pdf'),
                         file_name = FileName('Ogre_city_report.pdf'),
                         disposition = Disposition('attachment'),
                         content_id = ContentId('Example Content ID'))


# Second file for attchment
with open('report.html', 'rb') as f:
    html_data = f.read()
    f.close()
encoded_file = base64.b64encode(html_data).decode()
# Creates second instance attachedFile
attachedFile = Attachment(
            FileContent(encoded_file),
            FileName('Report.html'),
            FileType('application/html'),
            Disposition('attachment'))
message.attachment = attachment  # attaches pdf binary 
message.attachment = attachedFile  # attached second file Report.html


try:
    sendgrid_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
    response = sendgrid_client.send(message)
    print(response.status_code)
    print(response.body)
    print(response.headers)
except Exception as e:
    print(e.message)

