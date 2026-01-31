
#!/bin/bash
set -euo pipefail

# Download env files
aws s3 cp s3://sslv-ws-m5-cicd-files/.env.prod . || { echo "Failed to download .env.prod"; exit 1; }
aws s3 cp s3://sslv-ws-m5-cicd-files/database.ini . || { echo "Failed to download database.ini"; exit 1; }

# Fetch the secret from Secrets Manager
secret=$(aws secretsmanager get-secret-value --secret-id sslv_creds --query SecretString --output text) \
    || { echo "Failed to fetch secrets"; exit 1; }

# Parse all values in a single jq call
eval "$(jq -r '
    "export S3_BUCKET=\(.s3_db_backups | @sh)",
    "export SENDGRID_API_KEY=\(.sendgrid_api | @sh)",
    "export DEST_EMAIL=\(.dest_email | @sh)",
    "export SRC_EMAIL=\(.src_email | @sh)",
    "export RELEASE_VERSION=\(.release_version | @sh)"
' <<< "$secret")"

