#!/usr/bin/env python3
import boto3
import os

S3_BUCKET_NAME = os.environ['S3_BUCKET']
AWS_ACCESS_KEY_ID = os.environ['AWS_ACCESS_KEY_ID']
AWS_SECRET_ACCESS_KEY = os.environ['AWS_SECRET_ACCESS_KEY']
s3 = boto3.client('s3', region_name="eu-west-1", aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY)


def main() -> None:
    last_modifed_file_name = get_last_file_name(S3_BUCKET_NAME)
    download_file_from_s3(last_modifed_file_name)


def download_file_from_s3(remote_file_name: str ) -> None:
    """ Downloads file from AWS S3 bucket to current directory """
    curr_dir = os.getcwd()
    local_path_fn = curr_dir + "/" + remote_file_name
    try:
        s3.download_file(S3_BUCKET_NAME, remote_file_name, local_path_fn)
    except Exception as e:
        print(f"Error {e}")


def get_last_file_name(S3_BUCKET_NAME: str) -> str:
    """ Returns file name of object based on LastModified object attribute """
    get_last_modified = lambda obj: int(obj['LastModified'].strftime('%s'))
    objs = s3.list_objects_v2(Bucket=S3_BUCKET_NAME)['Contents']
    last_added = [obj['Key'] for obj in sorted(objs, key=get_last_modified, reverse=True)][0]
    return last_added


main()


