"""
sendgrid_mailer is used for sending emails with pdf attachments
"""
import base64
import os


from sendgrid.helpers.mail import (
    Mail, Attachment, FileContent, FileName,
    FileType, Disposition, ContentId)
from sendgrid import SendGridAPIClient

message = Mail(
    from_email=(os.environ.get('SRC_EMAIL')),
    to_emails=(os.environ.get('DEST_EMAIL')),
    subject='Ogre City Apartments for sale from ss.lv webscraper',
    html_content='<strong>Please find report in attachment</strong>')
file_path = 'Ogre_city_report.pdf'
with open(file_path, 'rb') as f:
    data = f.read()
    f.close()
encoded = base64.b64encode(data).decode()
attachment = Attachment()
attachment.file_content = FileContent(encoded)
attachment.file_type = FileType('application/pdf')
attachment.file_name = FileName('Ogre_city_report.pdf')
attachment.disposition = Disposition('attachment')
attachment.content_id = ContentId('Example Content ID')
message.attachment = attachment
try:
    sendgrid_client = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
    response = sendgrid_client.send(message)
    print(response.status_code)
    print(response.body)
    print(response.headers)
except Exception as e:
    print(e.message)
