
#!/bin/bash

# Fetch secret
secret=$(aws secretsmanager get-secret-value --secret-id sslv_creds --query SecretString --output text)

if [ $? -ne 0 ]; then
  echo "❌ Failed to fetch secret"
  return 1 2>/dev/null || exit 1
fi

echo "Sucessfully fetched secret..."
# Parse the value
S3_BUCKET=$(echo "$secret" | jq -r '.s3_db_backups')
SENDGRID_API_KEY=$(echo "$secret" | jq -r '.sendgrid_api')

echo "S3 bucket $S3_BUCKET will be used to fetch DB latest backup file... "


if [ -z "$S3_BUCKET" ] || [ "$S3_BUCKET" = "null" ]; then
  echo "❌ Failed to parse 's3_db_backups' from secret"
  return 1 2>/dev/null || exit 1
fi

if [ -z "$SENDGRID_API_KEY" ] || [ "$SENDGRID_API_KEY" = "null" ]; then
  echo "❌ Failed to parse 'sendgrid_api' from secret"
  return 1 2>/dev/null || exit 1
fi


#

# Export
export S3_BUCKET
echo "✅ S3_BUCKET env is set to: $S3_BUCKET"
export SENDGRID_API_KEY
echo "✅ SENDGRID_API_KEY env is set"


