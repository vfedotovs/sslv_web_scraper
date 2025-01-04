#!/bin/bash

# Set the file path and content variables
DB_CFG_FILE="database.ini"
DB_PASSWORD=$(openssl rand -base64 36 | tr -d '\n')

# echo "PG_PASS=$(openssl rand -base64 36 | tr -d '\n')" >> .env

# Create the file with the specified content
cat >"$DB_CFG_FILE" <<EOL
[postgresql]
host=db
database=webscraper
user=webscraper
password=$DB_PASSWORD
EOL

echo "File $DB_CFG_FILE created successfully."

# Set the file path and content variables
FILE=".env.prod"
DEST_EMAIL="source@example.local"
SRC_EMAIL="destination@example.local"
SENDGRID_API_KEY="<EXAMPLE_API_KEY_123>" # Replace with actual key

# Create the file with the specified content
cat >"$FILE" <<EOL
# ws_worker container envs
DEST_EMAIL=$DEST_EMAIL
SENDGRID_API_KEY=$SENDGRID_API_KEY
SRC_EMAIL=$SRC_EMAIL
PG_PASS=$DB_PASSWORD
EOL

echo "File $FILE created successfully."
