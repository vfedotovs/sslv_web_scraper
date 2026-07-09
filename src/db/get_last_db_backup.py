#!/usr/bin/env python3
"""
City-aware version of get_last_db_backup.py
Supports CITY env var or --city for per-city S3 buckets.
Usage:
  CITY=ogre python3 src/db/get_last_db_backup.py
  python3 src/db/get_last_db_backup.py --city salaspils --env prod
"""
import boto3
import os
import sys
import argparse

def get_bucket_name(city: str = None, env: str = "prod") -> str:
    if city:
        city_slug = city.replace("_", "-")
        return f"sslv-{env}-{city_slug}-db-backups"
    return os.environ.get('S3_BUCKET', '')

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", help="City slug (e.g. ogre, salaspils)")
    parser.add_argument("--env", default="prod", help="Environment (prod/staging/dev)")
    args = parser.parse_args()

    city = args.city or os.environ.get('CITY')
    env = args.env or os.environ.get('ENV', 'prod')

    bucket = get_bucket_name(city, env)
    if not bucket:
        print("ERROR: No S3 bucket. Set S3_BUCKET or use --city")
        sys.exit(1)

    print(f"Using S3 bucket: {bucket} (city={city}, env={env})")

    aws_access = os.environ.get('AWS_ACCESS_KEY_ID')
    aws_secret = os.environ.get('AWS_SECRET_ACCESS_KEY')
    s3 = boto3.client(
        's3',
        region_name=os.environ.get('AWS_REGION', 'eu-west-1'),
        aws_access_key_id=aws_access,
        aws_secret_access_key=aws_secret
    )

    last_file = get_last_file_name(s3, bucket)
    download_file_from_s3(s3, bucket, last_file)

def download_file_from_s3(s3, bucket: str, remote: str) -> None:
    curr_dir = os.getcwd()
    local = os.path.join(curr_dir, remote)
    try:
        s3.download_file(bucket, remote, local)
        print(f"Downloaded: {remote}")
    except Exception as e:
        print(f"Download error: {e}")
        sys.exit(1)

def get_last_file_name(s3, bucket: str) -> str:
    objs = s3.list_objects_v2(Bucket=bucket).get('Contents', [])
    if not objs:
        print(f"No objects in {bucket}")
        sys.exit(1)
    get_last = lambda obj: int(obj['LastModified'].strftime('%s'))
    return sorted(objs, key=get_last, reverse=True)[0]['Key']

if __name__ == "__main__":
    main()


