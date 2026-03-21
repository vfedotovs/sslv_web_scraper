#!/usr/bin/env python3


""" This module downloads latest file from AWS S3 bucket """
import gc
import os
import boto3
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import shutil
import sys


log = logging.getLogger('file_downloader')
log.setLevel(logging.INFO)
ws_log_format = logging.Formatter(
    "%(asctime)s [%(levelname)-5.5s] %(name)s: "
    "%(funcName)s: %(lineno)d: %(message)s")

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(ws_log_format)
log.addHandler(ch)

fh = handlers.RotatingFileHandler('s3_file_downloader.log',
                                  maxBytes=(1048576*5),
                                  backupCount=7)
fh.setFormatter(ws_log_format)
log.addHandler(fh)


# S3_BUCKET_NAME = os.environ['S3_BUCKET']
S3_LAMBDA_BUCKET_NAME = "lambda-ogre-scraped-data"
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')


def get_s3_client():
    """Create S3 client per-request instead of global to prevent memory leaks"""
    return boto3.client('s3', region_name="eu-west-1",
                       aws_access_key_id=AWS_ACCESS_KEY_ID,
                       aws_secret_access_key=AWS_SECRET_ACCESS_KEY)


def download_file_from_s3(s3_client, remote_file_name: str) -> None:
    """ Downloads file from AWS S3 bucket to current directory """
    curr_dir = os.getcwd()
    local_path_fn = curr_dir + "/" + remote_file_name
    log.info(f"Local path file name: {local_path_fn}")
    try:
        log.info(f"Trying to download rfn: {remote_file_name} "
                 f"to lfn: {local_path_fn} from S3:"
                 f" {S3_LAMBDA_BUCKET_NAME}")
        s3_client.download_file(S3_LAMBDA_BUCKET_NAME,
                                remote_file_name, local_path_fn)
    except Exception as err:
        print(f"Error {err}")
        log.error(f"File download failed with : {err}")


def get_last_file_name(s3_client, s3_bucket_name: str) -> str:
    """ Returns file name of object based on LastModified object attribute

    Memory optimization: Fetch all objects, sort in-place, and immediately
    extract only the key we need, then explicitly delete large variables.
    """
    log.info(f"Getting last object from S3 bucket {s3_bucket_name}")

    # Fetch objects from S3
    response = s3_client.list_objects_v2(Bucket=s3_bucket_name)
    objs = response.get('Contents', [])

    if not objs:
        log.error(f"No objects found in bucket {s3_bucket_name}")
        return None

    # Sort objects by LastModified (most recent first)
    objs.sort(key=lambda obj: obj['LastModified'], reverse=True)

    # Get the most recent file's key
    last_added = objs[0]['Key']
    log.info(f"Found last S3 bucket object: {last_added}")

    # Explicitly clean up large variables
    del objs
    del response

    return last_added


def move_file_to(folder: str, src_file_name: str, dst_file_name: str) -> None:
    """Moves file into the specified folder."""
    if not os.path.exists(folder):
        os.makedirs(folder)
    src_path = os.path.join(os.getcwd(), src_file_name)
    dst_path = os.path.join(folder, dst_file_name)
    try:
        shutil.move(src_path, dst_path)
        log.info(f"File {src_file_name} moved to {dst_path}")
    except Exception as e:
        log.error(f"Error moving {src_file_name} to {dst_path}: {e}")


def download_latest_lambda_file() -> None:
    """ Main entry point

    Memory optimization: Create S3 client per-request, use it, then
    explicitly clean it up to prevent memory leaks from boto3 caching.
    """
    # Create S3 client for this request only
    s3_client = get_s3_client()

    try:
        # Get the last modified file name
        last_modified_file_name = get_last_file_name(s3_client, S3_LAMBDA_BUCKET_NAME)

        if last_modified_file_name is None:
            log.error("No file found to download from S3")
            return

        # Download the file
        download_file_from_s3(s3_client, last_modified_file_name)
        log.info(f"File {last_modified_file_name} download was successful")

        # Move file to destination folder
        move_file_to('local_lambda_raw_scraped_data',
                     last_modified_file_name,
                     last_modified_file_name)

    finally:
        # Explicitly cleanup S3 client and force garbage collection
        del s3_client
        gc.collect()
        log.info("S3 client cleaned up and memory freed")


if __name__ == "__main__":
    download_latest_lambda_file()
