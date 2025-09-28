#!/usr/bin/env python3

"""aws_mailer.py module

Main usage case for this module:
    1. Send email using AWS SES service
    3. Add ad oneline information about each apartment in email body
    4. Use environemt varibales for source/destination email and API key

Tasks:
[x] task 01 - test email is getting sent with success
[x] task 02 - tmp files are deleted after email sent functionality
[x] task 03 - dynamic email title functionality (city name, version, deploy date)
[ ] task 04 - email body contains adverts data for 1-6 room categories
[ ] task 05 - email body contains medatada/debug info

"""

import boto3
from botocore.exceptions import ClientError
from datetime import datetime
import logging
from logging import handlers
import sys
import os
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


data_files = [
    "email_body_txt_m4.txt",
    "Mailer_report.txt",
    "Ogre-raw-data-report.txt",
    "cleaned-sorted-df.csv",
    "pandas_df.csv",
    "basic_price_stats.txt",
    "email_body_add_dates_table.txt",
    "1_rooms_tmp.txt",
    "mrv2.txt",
]


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


def gen_subject_title() -> str:
    """Function generates uniq subject line to improve debugging
    Example of subject:
    Ogre City Apartments for sale from ss.lv webscraper v1.4.8 20221001_1019"""
    log.info("Generating email subject with todays date")
    release = "1.5.10"
    # RELEASE_VERSION = os.environ['RELEASE_VERSION']
    now = datetime.now()
    email_created = now.strftime("%Y%m%d_%H%M")
    city_name = "Ogre City Apartments for sale from ss.lv web_scraper_v"
    email_subject = city_name + release + "_" + email_created
    subject_ver = email_subject.split("ss.lv")[1]
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
        with open(file_name, "r", encoding="utf-8") as file_object:
            # Read file in to list
            log.info(f"Trying to read file {file_name} contents.")
            file_content = file_object.readlines()
            # Convert list to string with no space as separator
            extracted_file_contents = "".join(file_content)
            extracted_file_contents += "\n\n"
            return extracted_file_contents
    except FileNotFoundError:
        log.error(f"FileNotFoundError: file {file_name} not found.")
        extracted_file_contents = (
            "\n\nFileNotFoundError: "
            + file_name
            + " Please contact the developer team to provide feedback."
        )
        # Return an empty string or a default value to avoid further errors
        return extracted_file_contents
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")
        extracted_file_contents = (
            "\n\nUnexpected error: file " + file_name + " was not found. "
            "Please contact the developer team to provide feedback."
        )
        return extracted_file_contents


def aws_mailer_main():
    log.info("--- AWS SES mailer module started ---")

    SENDER = "info@propertydata.lv"
    RECIPIENT = "info@propertydata.lv"
    AWS_REGION = "eu-west-1"  # e.g., Ireland
    SUBJECT = gen_subject_title()
    # TEXT_SECTION_URLS = extract_file_contents("email_body_txt_m4.txt")

    with open("email_body_txt_m4.txt_orig", "r", encoding="utf-8") as f:
        BODY_TEXT = f.read()

    # List the files you want to append in order
    extra_files = [
        "basic_price_stats.txt",
        "email_body_add_dates_table.txt",
        "scraped_and_removed.txt",
    ]

    # Append contents of each file
    for filename in extra_files:
        try:
            with open(filename, "r", encoding="utf-8") as ef:
                BODY_TEXT += "\n\n" + ef.read()
            log.info(f"Appended contents of {filename} to BODY_TXT")
        except FileNotFoundError:
            log.warning(f"Missing file: {filename} — continuing without it.")

    log.info(f"--- Final email body length: {len(BODY_TEXT)} ")

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
    remove_tmp_files(data_files)


if __name__ == "__main__":
    aws_mailer_main()
