#!/bin/bash

# Download env files
aws s3 cp s3://sslv-ws-m5-cicd-files/.env.prod .
aws s3 cp s3://sslv-ws-m5-cicd-files/database.ini .

# Fetch the secret from Secrets Manager
secret=$(aws secretsmanager get-secret-value --secret-id sslv_creds --query SecretString --output text)

# Parse the JSON to get individual values
export S3_BUCKET=$(echo $secret | jq -r '.s3_db_backups')
export DEST_EMAIL=$(echo $secret | jq -r '.dest_email')
export SRC_EMAIL=$(echo $secret | jq -r '.src_email')
