#!/bin/bash

# All AWS resources (S3 bucket + sslv_creds secret) live in eu-west-1.
# Pin the region explicitly so this script works from any EC2 region —
# Secrets Manager is region-scoped and won't auto-redirect like S3 does.
AWS_RES_REGION="${AWS_RES_REGION:-eu-west-1}"

# Download env files
aws --region "$AWS_RES_REGION" s3 cp s3://sslv-ws-m5-cicd-files/.env.prod .
aws --region "$AWS_RES_REGION" s3 cp s3://sslv-ws-m5-cicd-files/database.ini .

# Fetch the secret from Secrets Manager
secret=$(aws --region "$AWS_RES_REGION" secretsmanager get-secret-value \
    --secret-id sslv_creds --query SecretString --output text)

# Parse the JSON to get individual values
export S3_BUCKET=$(echo $secret | jq -r '.s3_db_backups')
export DEST_EMAIL=$(echo $secret | jq -r '.dest_email')
export SRC_EMAIL=$(echo $secret | jq -r '.src_email')
