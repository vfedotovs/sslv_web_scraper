#!/bin/bash

# Set your S3 bucket name
secret=$(aws secretsmanager get-secret-value --secret-id sslv_creds --query SecretString --output text)
S3_BUCKET=$(echo $secret | jq -r '.s3_db_backups')

# Fetch the latest uploaded file from the S3 bucket using AWS CLI
# We use the `aws s3api` to list objects sorted by LastModified date, in descending order.
LATEST_FILE=$(aws s3api list-objects-v2 --bucket "$S3_BUCKET" --query 'Contents | sort_by(@, &LastModified)[-1].Key' --output text)

# Check if the file was found
if [ -z "$LATEST_FILE" ]; then
  echo "No files found in the bucket: $S3_BUCKET"
  exit 1
fi

# Download the latest file to the current directory
echo "Downloading latest file: $LATEST_FILE from S3 bucket: $S3_BUCKET"
aws s3 cp "s3://$S3_BUCKET/$LATEST_FILE" .

# Check if the download was successful
if [ $? -eq 0 ]; then
  echo "File downloaded successfully: $LATEST_FILE"
else
  echo "Failed to download file: $LATEST_FILE"
  exit 1
fi
