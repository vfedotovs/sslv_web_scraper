""" This module downloads latest file from AWS S3 bucket """
import os
import boto3
import logging
from logging import handlers
from logging.handlers import RotatingFileHandler
import sys


log = logging.getLogger('file_downloader')
log.setLevel(logging.INFO)
ws_log_format = logging.Formatter(
    "%(asctime)s [%(threadName)-12.12s] "
    " [%(levelname)-5.5s] %(name)s : "
    "%(funcName)s: %(lineno)d: %(message)s")

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(ws_log_format)
log.addHandler(ch)

fh = handlers.RotatingFileHandler('file_downloader.log',
                                  maxBytes=(1048576*5),
                                  backupCount=7)
fh.setFormatter(ws_log_format)
log.addHandler(fh)


# S3_BUCKET_NAME = os.environ['S3_BUCKET']
S3_LAMBDA_BUCKET_NAME = "lambda-ogre-scraped-data"
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
s3 = boto3.client('s3', region_name="eu-west-1",
                  aws_access_key_id=AWS_ACCESS_KEY_ID,
                  aws_secret_access_key=AWS_SECRET_ACCESS_KEY)


def download_file_from_s3(remote_file_name: str) -> None:
    """ Downloads file from AWS S3 bucket to current directory """
    curr_dir = os.getcwd()
    local_path_fn = curr_dir + "/" + remote_file_name
    log.info(f"Local path file name: {local_path_fn}")
    try:
        log.info(f"Trying to download rfn: {remote_file_name} "
                 f"to lfn: {local_path_fn} from S3:"
                 f" {S3_LAMBDA_BUCKET_NAME}")
        s3.download_file(S3_LAMBDA_BUCKET_NAME,
                         remote_file_name, local_path_fn)
    except Exception as err:
        print(f"Error {err}")
        log.error(f"File download failed with : {err}")


def get_last_file_name(s3_bucket_name: str) -> str:
    """ Returns file name of object based on LastModified object attribute """
    log.info(f"Getting last object from S3 buncked {s3_bucket_name}")
    def get_last_modified(obj): return int(obj['LastModified'].strftime('%s'))
    objs = s3.list_objects_v2(Bucket=s3_bucket_name)['Contents']
    last_added = [obj['Key'] for obj in sorted(objs,
                                               key=get_last_modified,
                                               reverse=True)][0]
    log.info(f"Found last S3 bucket object {last_added}")
    return last_added


def move_file_to(folder: str, src_file_name: str, dst_file_name: str) -> None:
    """ Moves file in to local_lambda_raw_scraped_data folder"""
    move_cmd = 'mv ' + src_file_name + ' ' + folder + '/' + dst_file_name
    if not os.path.exists(folder):
        os.makedirs(folder)
    os.system(move_cmd)
    log.info(f"Command: {move_cmd} was completed")


def download_latest_lambda_file() -> None:
    """ Main entry point """
    last_modifed_file_name = get_last_file_name(S3_LAMBDA_BUCKET_NAME)
    download_file_from_s3(last_modifed_file_name)
    log.info(f"File {last_modifed_file_name} download was sucessfull")
    move_file_to('local_lambda_raw_scraped_data',
                 last_modifed_file_name,
                 last_modifed_file_name)


download_latest_lambda_file()
