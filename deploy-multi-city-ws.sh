#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config/cities.yaml"
LOG_FILE="${SCRIPT_DIR}/deploy-multi-city.log"

# Logging function with timestamp
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

log_info() {
    log "INFO" "$@"
}

log_error() {
    log "ERROR" "$@"
}

log_warn() {
    log "WARN" "$@"
}

# Check if config file exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    log_error "Cities configuration file not found: $CONFIG_FILE"
    exit 1
fi

# Parse city names from YAML
# Extracts top-level keys directly under the 'cities:' section.
parse_cities() {
    local yaml_file="$1"
    if [[ ! -f "$yaml_file" ]]; then
        echo ""
        return 1
    fi

    # Pure bash parser for this simple YAML structure (2-space indent)
    awk '
        /^cities:/ { in_cities=1; next }
        in_cities && /^[[:space:]]{2}[a-zA-Z0-9_]+:/ {
            gsub(/:/, "", $1)
            gsub(/^[[:space:]]+/, "", $1)
            print $1
        }
        in_cities && /^[a-zA-Z_]/ && !/^cities:/ { exit }
    ' "$yaml_file"
}

# Get list of cities (portable, works on macOS bash 3.2+)
CITIES=()
while IFS= read -r city; do
    [[ -n "$city" ]] && CITIES+=("$city")
done < <(parse_cities "$CONFIG_FILE")

if [[ ${#CITIES[@]} -eq 0 ]]; then
    log_error "No cities found in $CONFIG_FILE"
    exit 1
fi

log_info "Found ${#CITIES[@]} cities to deploy: ${CITIES[*]}"

# Detect docker compose command
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    log_error "Neither 'docker compose' nor 'docker-compose' found"
    exit 1
fi

log_info "Using compose command: $COMPOSE_CMD"

# Check common files once (outside per-city loop)
if [[ ! -f "docker-compose.yml" ]]; then
    log_error "docker-compose.yml not found in current directory"
    exit 1
fi

# Load common secrets/config from helper scripts (Secrets Manager / S3) if present.
# These populate shell env for compose or other tools. Per-city .env.* files (for CITY_ vars etc)
# are still handled explicitly via ensure_env_file below (download on demand).
if [ -f "scripts/set_s3_env_from_aws_sm.sh" ]; then
    log_info "Loading secrets from AWS Secrets Manager..."
    source "scripts/set_s3_env_from_aws_sm.sh" 2>/dev/null || log_warn "Could not source set_s3_env_from_aws_sm.sh"
fi

if [ -f "scripts/load_secrets.sh" ]; then
    log_info "Loading additional secrets and config from S3..."
    source "scripts/load_secrets.sh" 2>/dev/null || log_warn "Could not source load_secrets.sh"
fi

# Optional: allow overriding the cicd files bucket
CICD_FILES_BUCKET=${CICD_FILES_BUCKET:-sslv-ws-m5-cicd-files}

# Ensure per-city .env file exists on disk.
# Downloads from S3 (CICD_FILES_BUCKET) using AWS IAM credentials if missing.
# This allows the script to work on fresh hosts without .env.* pre-existing on disk.
# No secrets are printed or leaked by this logic.
ensure_env_file() {
    local city="$1"
    local env_file=".env.${city}"

    if [[ -f "$env_file" ]]; then
        log_info "Using existing $env_file on disk"
        return 0
    fi

    log_info "Downloading $env_file from s3://${CICD_FILES_BUCKET}/ (using IAM)..."
    if aws s3 cp "s3://${CICD_FILES_BUCKET}/${env_file}" "$env_file" --quiet 2>&1; then
        log_info "Downloaded $env_file successfully"
        # Protect the file (contains secrets)
        chmod 600 "$env_file" 2>/dev/null || true
        return 0
    else
        log_error "Failed to download $env_file from s3://${CICD_FILES_BUCKET}/"
        log_error "Check: file exists in bucket, AWS credentials/IAM role has s3:GetObject, and aws cli is configured."
        return 1
    fi
}

SUCCESS_COUNT=0
FAIL_COUNT=0
FAILED_CITIES=()

for city in "${CITIES[@]}"; do
    env_file=".env.${city}"
    
    log_info "Starting deployment for city: $city"
    
    if ! ensure_env_file "$city"; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_CITIES+=("$city")
        continue
    fi
    
    log_info "Deploying $city using $env_file ..."
    
    # Run docker compose with project name
    if $COMPOSE_CMD --project-name "$city" --env-file "$env_file" up -d; then
        log_info "Successfully deployed $city"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        log_error "Failed to deploy $city"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_CITIES+=("$city")
    fi
done

echo ""
log_info "Deployment summary:"
log_info "  Total cities: ${#CITIES[@]}"
log_info "  Successful:   $SUCCESS_COUNT"
log_info "  Failed:       $FAIL_COUNT"

if [[ $FAIL_COUNT -gt 0 ]]; then
    log_error "Failed cities: ${FAILED_CITIES[*]}"
    log_error "Deployment completed with errors."
    exit 1
else
    log_info "All cities deployed successfully."
    exit 0
fi
