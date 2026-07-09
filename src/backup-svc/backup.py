import boto3
import subprocess
import datetime
import os
import sys

def backup_postgres():
    # Get config from environment
    db_host = os.environ.get('DB_HOST', 'db')
    db_user = os.environ.get('DB_USER', 'new_docker_user')
    db_name = os.environ.get('DB_NAME', 'new_docker_db')
    db_password = os.environ.get('POSTGRES_PASSWORD', os.environ.get('DB_PASSWORD', ''))
    
    s3_bucket = os.environ.get('S3_BUCKET')
    if not s3_bucket:
        print("ERROR: S3_BUCKET environment variable not set")
        sys.exit(1)
    
    # Generate backup filename with current date
    now = datetime.datetime.now()
    date_str = now.strftime("%Y_%m_%d")
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    backup_filename = f"/tmp/pg_backup_{timestamp}.sql"
    gzip_filename = f"{backup_filename}.gz"
    
    # Run pg_dump
    print(f"Starting pg_dump for {db_name} on {db_host}...")
    try:
        env = os.environ.copy()
        env['PGPASSWORD'] = db_password
        subprocess.run(
            [
                "pg_dump",
                "-h", db_host,
                "-U", db_user,
                "-d", db_name,
                "-f", backup_filename,
            ],
            env=env,
            check=True,
        )
        print("pg_dump completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"pg_dump failed: {e}")
        sys.exit(1)
    
    # Compress
    print("Compressing backup...")
    subprocess.run(["gzip", "-f", backup_filename], check=True)
    
    return gzip_filename

def upload_to_s3(file_path, bucket_name):
    s3_client = boto3.client('s3')
    
    # Key with date structure
    now = datetime.datetime.now()
    key = f"db-backups/{now.strftime('%Y')}/{now.strftime('%m')}/{now.strftime('%d')}/pg_backup_{now.strftime('%Y%m%d_%H%M%S')}.sql.gz"
    
    try:
        s3_client.upload_file(file_path, bucket_name, key)
        print(f"Uploaded {file_path} to s3://{bucket_name}/{key}")
    except Exception as e:
        print(f"Failed to upload to S3: {e}")
        sys.exit(1)

if __name__ == "__main__":
    backup_file = backup_postgres()
    s3_bucket = os.environ.get('S3_BUCKET')
    upload_to_s3(backup_file, s3_bucket)
    # Cleanup
    os.remove(backup_file)
    print("Backup completed and cleaned up.")
