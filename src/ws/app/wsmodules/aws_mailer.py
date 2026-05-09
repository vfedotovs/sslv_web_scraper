#!/usr/bin/env python3

"""Send the daily Ogre apartment scrape report via AWS SES.

Assembles the email body from text files produced by upstream pipeline
modules (df_cleaner, db_worker, run_analisys), generates a dynamic
subject line that includes release version and deployment environment,
sends the message through AWS SES, and removes the scratch files.

Required environment variables:
    SRC_EMAIL              Sender address (falls back to info@propertydata.lv)
    DEST_EMAIL             Recipient address (falls back to info@propertydata.lv)
    AWS_REGION             SES region (falls back to eu-west-1)
    RELEASE_VERSION        Used in the email subject (falls back to 'unknown')
    APP_ENV                Used in the email subject (falls back to 'local')
    AWS_MAILER_LOG_PATH    Path for the rotating log file (falls back to './aws_mailer.log')

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

_LOG_FILE_PATH = os.environ.get("AWS_MAILER_LOG_PATH", "aws_mailer.log")


def _configure_logging() -> None:
    """Idempotently attach stdout and rotating-file handlers to the module logger.

    Safe to call multiple times — the handler guard check skips re-attach
    so file descriptors don't leak across worker restarts. Called at the
    start of aws_mailer_main(); other entry points that want module logging
    should call this too.
    """
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5.5s] : %(funcName)s: %(lineno)d: %(message)s"
    )
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = handlers.RotatingFileHandler(
        _LOG_FILE_PATH, maxBytes=(1048576 * 5), backupCount=7
    )
    fh.setFormatter(fmt)
    log.addHandler(fh)


_EMAIL_MAIN_FILE = "email_body_txt_m4.txt"

# Files appended to the email body in order. scraped_and_removed.txt is
# preserved on disk between runs (matches historical behavior).
_EMAIL_EXTRA_FILES = [
    "basic_price_stats.txt",
    "email_body_add_dates_table.txt",
    "scraped_and_removed.txt",
]

# Files explicitly NOT cleaned by remove_tmp_files() after sending.
_PRESERVED_FILES = {"scraped_and_removed.txt"}

# Scratch artifacts produced by upstream pipeline modules (df_cleaner,
# db_worker, run_analisys) that are not part of the email body.
_OTHER_SCRATCH_FILES = [
    "Mailer_report.txt",
    "Ogre-raw-data-report.txt",
    "cleaned-sorted-df.csv",
    "pandas_df.csv",
    "1_rooms_tmp.txt",
    "mrv2.txt",
]

# Single source of truth for files removed after the email is sent.
# Derived so adding a file above (extras or scratch) auto-includes it
# in cleanup, unless it's also in _PRESERVED_FILES.
data_files = [
    f for f in [_EMAIL_MAIN_FILE, *_EMAIL_EXTRA_FILES, *_OTHER_SCRATCH_FILES]
    if f not in _PRESERVED_FILES
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
    """Read a UTF-8 text file and return its contents with a trailing blank line.

    Used to assemble the email body — the trailing `\n\n` separates this
    file's contents from whatever comes next.

    Recoverable errors (file missing, permission denied, encoding error,
    path is a directory) are logged and returned as a human-readable
    fallback string so a bad input file degrades gracefully rather than
    aborting the mailer. Programming errors propagate unchanged.

    Args:
        file_name: Path to the file to read.

    Returns:
        File contents plus `"\n\n"`, or a fallback message describing
        the recoverable error encountered.
    """
    try:
        with open(file_name, "r", encoding="utf-8") as file_object:
            log.info(f"Trying to read file {file_name} contents.")
            return "".join(file_object.readlines()) + "\n\n"
    except FileNotFoundError:
        log.error(f"FileNotFoundError: file {file_name} not found.")
        return (
            f"\n\nFileNotFoundError: {file_name}"
            " Please contact the developer team to provide feedback."
        )
    except (UnicodeDecodeError, PermissionError, IsADirectoryError) as e:
        log.error(f"Error reading {file_name}: {e}")
        return (
            f"\n\nError reading {file_name}: {e}. "
            "Please contact the developer team to provide feedback."
        )


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
    _configure_logging()
    log.info("--- AWS SES mailer module started ---")

    SENDER = os.environ.get('SRC_EMAIL', 'info@propertydata.lv')
    RECIPIENT = os.environ.get('DEST_EMAIL', 'info@propertydata.lv')
    AWS_REGION = os.environ.get('AWS_REGION', 'eu-west-1')
    SUBJECT = gen_subject_title()

    BODY_TEXT = extract_file_contents(_EMAIL_MAIN_FILE)

    for filename in _EMAIL_EXTRA_FILES:
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
