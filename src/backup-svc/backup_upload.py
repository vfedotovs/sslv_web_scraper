import boto3
import subprocess
import datetime
import os


def backup_postgres():
    # Define backup filename with current date
    date_str = datetime.datetime.now().strftime("%Y_%m_%d")
    backup_filename = f"/tmp/pg_backup_{date_str}.sql"

    # Run pg_dump command to create the backup
    subprocess.run(
        [
            "pg_dump",
            "-U",
            "DB-USER",
            "-h",
            "db",  # Assuming the db container is named `db` in the network
            "-d",
            "DB-NAME",
            "-f",
            backup_filename,
        ],
        check=True,
    )

    return backup_filename


def upload_to_s3(file_path, bucket_name, object_name=None):
    # Initialize the boto3 client
    s3_client = boto3.client(
        "s3", region_name="your-region"
    )  # Replace 'your-region' with your S3 region

    # Define object name in S3 if not provided
    if not object_name:
        object_name = os.path.basename(file_path)

    # Upload the file to the specified S3 bucket
    s3_client.upload_file(file_path, bucket_name, object_name)
    print(f"Uploaded {file_path} to S3 bucket {bucket_name}")


if __name__ == "__main__":
    # Generate the backup
    backup_file = backup_postgres()

    # Upload backup to S3
    s3_bucket_name = "bucket-name-pg-backups"  # Replace with your bucket name
    upload_to_s3(backup_file, s3_bucket_name)
