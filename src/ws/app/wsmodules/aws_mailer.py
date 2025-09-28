#!/usr/bin/env python3

import boto3
from botocore.exceptions import ClientError
import logging
from logging import handlers
import sys
from logging.handlers import RotatingFileHandler


log = logging.getLogger("aws_mailer")
log.setLevel(logging.INFO)
fa_log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s"
)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fa_log_format)
log.addHandler(ch)
fh = handlers.RotatingFileHandler(
    "aws_mailer.log", maxBytes=(1048576 * 5), backupCount=7
)
fh.setFormatter(fa_log_format)
log.addHandler(fh)


def aws_mailer_main():
    log.info("--- AWS SES mailer module started ---")

    SENDER = "info@propertydata.lv"
    RECIPIENT = "info@propertydata.lv"
    AWS_REGION = "eu-west-1"  # e.g., Ireland
    SUBJECT = "Test email from Amazon SES (via Python)"
    BODY_TEXT = (
        "Hello!\nThis is a test email sent using Amazon SES with Python and Boto3."
    )
    BODY_HTML = """<html>
    <head></head>
    <body>
      <h1>Hello!</h1>
      <p>This is a test email sent using <b>Amazon SES</b> with Python and Boto3.</p>
    </body>
    </html>
    """
    CHARSET = "UTF-8"

    log.info("Creating AWS SES clinet using boto3 ")
    client = boto3.client("ses", region_name=AWS_REGION)

    log.info("Trying to sent email with AWS SES clinet using boto3 ")
    try:
        response = client.send_email(
            Destination={
                "ToAddresses": [
                    RECIPIENT,
                ],
            },
            Message={
                "Body": {
                    "Html": {
                        "Charset": CHARSET,
                        "Data": BODY_HTML,
                    },
                    "Text": {
                        "Charset": CHARSET,
                        "Data": BODY_TEXT,
                    },
                },
                "Subject": {
                    "Charset": CHARSET,
                    "Data": SUBJECT,
                },
            },
            Source=SENDER,
        )
    except ClientError as e:
        print(f"Failed to send email: {e.response['Error']['Message']}")
        log.error(f"Failed to send email: {e.response['Error']['Message']}")
    else:
        print(f"Email sent! Message ID: {response['MessageId']}")
        log.info(f"Email sent! Message ID: {response['MessageId']}")
    log.info("--- AWS SES mailer module completed with succeess ---")


if __name__ == "__main__":
    aws_mailer_main()
