#!/usr/bin/env python3

"""Send the daily Ogre apartment scrape report via AWS SES.

Assembles the email body from text files produced by upstream pipeline
modules (df_cleaner, db_worker, run_analisys), generates a dynamic
subject line that includes release version and deployment environment,
sends the message through AWS SES, and removes the scratch files.

Required environment variables:
    SRC_EMAIL          Sender address (falls back to info@propertydata.lv)
    DEST_EMAIL         Recipient address (falls back to info@propertydata.lv)
    AWS_REGION         SES region (falls back to eu-west-1)
    RELEASE_VERSION    Used in the email subject (falls back to 'unknown')
    APP_ENV            Used in the email subject (falls back to 'local')

AWS credentials must be available via the standard boto3 chain
(instance profile, env vars, or ~/.aws/credentials).
"""

from datetime import datetime
import logging
from logging import handlers
import sys
import os
import boto3
from botocore.exceptions import ClientError


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
    """Best-effort delete of a list of temp files in the current working directory.

    Per-file errors are logged but do not abort the loop — used post-send
    to clean up scratch files left by upstream modules. Missing files are
    treated as ordinary errors and logged at error level.

    Args:
        files_to_remove: List of filenames (relative to cwd) to delete.
    """
    directory = os.getcwd()
    log.info(f"Attempting clean temp files from {directory} folder")
    for file in files_to_remove:
        try:
            log.info(f"Trying to deleting file: {file} ")
            os.remove(file)
            log.info(f"File: {file} deleted with success ")
        except OSError as e:
            log.error(f"Failed to delete {file}: {e}")


def gen_subject_title() -> str:
    """Generate a unique email subject line tagged with version and environment.

    The subject embeds the current timestamp, the deploy's RELEASE_VERSION
    env var (or 'unknown' if unset), and the APP_ENV env var (or 'local'
    if unset) in square brackets — making it trivial to identify which
    deploy produced which email.

    Returns:
        A subject string of the form
        "Ogre City Apartments for sale from ss.lv web_scraper_<version>_<YYYYMMDD>_<HHMM> [<env>]".
    """
    log.info("Generating email subject with todays date")
    release = os.environ.get('RELEASE_VERSION', 'unknown')
    app_env = os.environ.get('APP_ENV', 'local')
    now = datetime.now()
    email_created = now.strftime("%Y%m%d_%H%M")
    email_subject = (
        f"Ogre City Apartments for sale from ss.lv web_scraper_"
        f"{release}_{email_created} [{app_env}]"
    )
    log.info(f"Email subject: {email_subject}")
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


def aws_mailer_main() -> None:
    """
    Send an email using AWS Simple Email Service (SES) with content assembled from multiple text files.

    This function:
      - Logs the start and end of the mailer execution.
      - Reads the main email body text from `email_body_txt_m4.txt`.
      - Attempts to append additional content from optional files:
          * basic_price_stats.txt
          * email_body_add_dates_table.txt
          * scraped_and_removed.txt
        If any of these files are missing, it logs a warning and continues without them.
      - Generates the email subject dynamically using `gen_subject_title()`.
      - Sends the email via AWS SES with the specified sender and recipient addresses.
      - Logs the success or failure of the send operation.
      - Cleans up temporary data files after sending.

    Prerequisites:
      - AWS credentials configured for boto3 to access SES.
      - All required text files present in the current working directory.

    Raises:
      botocore.exceptions.ClientError: If sending the email via AWS SES fails.

    Returns:
      None
    """
    log.info("--- AWS SES mailer module started ---")

    SENDER = os.environ.get('SRC_EMAIL', 'info@propertydata.lv')
    RECIPIENT = os.environ.get('DEST_EMAIL', 'info@propertydata.lv')
    AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-1')
    SUBJECT = gen_subject_title()

    BODY_TEXT = extract_file_contents("email_body_txt_m4.txt")

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

    log.info("Creating AWS SES client using boto3")
    client = boto3.client("ses", region_name=AWS_REGION)

    log.info("Trying to send email with AWS SES client using boto3")
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
        log.error(f"Failed to send email: {e.response['Error']['Message']}")
    else:
        log.info(f"Email sent! Message ID: {response['MessageId']}")
    log.info("--- AWS SES mailer module completed with success ---")
    remove_tmp_files(data_files)


if __name__ == "__main__":
    aws_mailer_main()
