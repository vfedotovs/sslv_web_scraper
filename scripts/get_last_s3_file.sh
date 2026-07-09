#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config/cities.yaml"

# Defaults
ENV="prod"
CITY=""
ALL=false

usage() {
  echo "Usage: $0 [--city CITY] [--env prod|staging|dev] [--all]"
  echo "  --city CITY   Use per-city S3 bucket (e.g. sslv-prod-ogre-db-backups)"
  echo "  --all         Process all cities from config/cities.yaml"
  echo "  --env ENV     Environment prefix (default: prod)"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --city) CITY="$2"; shift 2 ;;
    --all) ALL=true; shift ;;
    --env) ENV="$2"; shift 2 ;;
    --help|-h) usage ;;
    *) echo "Unknown option $1"; usage ;;
  esac
done

# Parse cities (same logic as backup script)
parse_cities() {
  awk '
    /^cities:/ { in_cities=1; next }
    in_cities && /^[[:space:]]{2}[a-zA-Z0-9_]+:/ {
      city = $0; gsub(/^[[:space:]]+/, "", city); sub(/:.*/, "", city);
      if (city != "") print city
    }
    in_cities && /^[^[:space:]][a-zA-Z_]/ && !/^cities:/ { exit }
  ' "$1"
}

get_cities() {
  if [[ "$ALL" == true ]]; then
    parse_cities "$CONFIG_FILE"
  elif [[ -n "$CITY" ]]; then
    echo "$CITY"
  else
    echo ""
  fi
}

get_s3_bucket() {
  local city="$1"
  local env="$2"
  # Prefer S3_BUCKET from .env.${city} if present
  local env_file=".env.${city}"
  if [[ -f "$env_file" ]]; then
    # shellcheck disable=SC1090
    S3_BUCKET=$(grep -E '^S3_BUCKET=' "$env_file" | head -1 | cut -d= -f2- | tr -d '"' || true)
    if [[ -n "${S3_BUCKET:-}" ]]; then
      echo "$S3_BUCKET"
      return
    fi
  fi
  # Fallback to convention
  local city_slug="${city//_/-}"
  echo "sslv-${env}-${city_slug}-db-backups"
}

download_latest() {
  local city="$1"
  local s3_bucket
  s3_bucket=$(get_s3_bucket "$city" "$ENV")

  echo "Fetching latest from bucket: $s3_bucket (city: $city)"

  LATEST_FILE=$(aws s3api list-objects-v2 --bucket "$s3_bucket" --query 'Contents | sort_by(@, &LastModified)[-1].Key' --output text 2>/dev/null || echo "")

  if [[ -z "$LATEST_FILE" || "$LATEST_FILE" == "None" ]]; then
    echo "No files found in the bucket: $s3_bucket"
    return 1
  fi

  local out_name
  if [[ -n "$city" ]]; then
    out_name="${city}-$(basename "$LATEST_FILE")"
  else
    out_name="$(basename "$LATEST_FILE")"
  fi

  echo "Downloading latest file: $LATEST_FILE from $s3_bucket as $out_name"
  aws s3 cp "s3://$s3_bucket/$LATEST_FILE" "./$out_name"

  if [[ $? -eq 0 ]]; then
    echo "File downloaded successfully: $out_name"
  else
    echo "Failed to download file: $out_name"
    return 1
  fi
}

CITIES=$(get_cities)

if [[ -z "$CITIES" ]]; then
  # Legacy fallback: use secret
  secret=$(aws secretsmanager get-secret-value --secret-id sslv_creds --query SecretString --output text)
  S3_BUCKET=$(echo $secret | jq -r '.s3_db_backups')
  download_latest "" || exit 1
else
  for city in $CITIES; do
    download_latest "$city" || echo "Warning: failed for $city" >&2
  done
fi

