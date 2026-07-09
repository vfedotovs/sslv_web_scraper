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

    # Awk parser for the simple "cities:\n  cityname:\n    ..." YAML.
    # IMPORTANT: We copy the line into a variable instead of modifying $1/$0.
    # Modifying awk fields causes it to rebuild $0 (using OFS), which
    # can falsely trigger the "stop on next top-level key" rule on the
    # very first city (the root cause of "only 1 city found").
    awk '
        /^cities:/ { in_cities=1; next }
        in_cities && /^[[:space:]]{2}[a-zA-Z0-9_]+:/ {
            city = $0
            gsub(/^[[:space:]]+/, "", city)
            sub(/:.*/, "", city)
            if (city != "") print city
        }
        # Stop when we hit a new top-level key (line does not start with whitespace)
        in_cities && /^[^[:space:]][a-zA-Z_]/ && !/^cities:/ { exit }
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
# For M6 staging deployments, default to the dedicated staging CICD bucket
CICD_FILES_BUCKET=${CICD_FILES_BUCKET:-sslv-staging-m6-cicd-files}

# Ensure database.ini is present in the ws build context.
# src/ws/Dockerfile does: COPY database.ini /
# load_secrets.sh downloads it to the project root, matching Makefile setup behavior.
if [[ -f "database.ini" ]]; then
    mkdir -p src/ws
    if ! cmp -s database.ini src/ws/database.ini 2>/dev/null; then
        cp -f database.ini src/ws/database.ini
        log_info "Copied database.ini into src/ws/ for Docker build context"
    fi
fi

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

# Pre-deploy safety check for backup age (non-fatal warning only)
# Note: Restore is manual. Use scripts/restore_db_city.sh if needed.
check_backup_age() {
    local city="$1"
    local env="${M6_ENV:-prod}"
    local city_slug="${city//_/-}"
    local bucket="sslv-${env}-${city_slug}-db-backups"
    
    local latest=$(aws s3 ls "s3://${bucket}/db-backups/" --recursive 2>/dev/null | sort | tail -1 | awk '{print $1}')
    if [ -z "$latest" ]; then
        log_warn "[LOW BACKUP] No backup found for $city in $bucket"
        return
    fi
    
    # Extract date from path like db-backups/2026/07/09/...
    local bdate=$(echo "$latest" | cut -d/ -f1-3 | tr / _ )
    if [ -z "$bdate" ]; then
        log_warn "[LOW BACKUP] Could not parse backup date for $city"
        return
    fi
    
    local bepoch=$(date -j -f "%Y_%m_%d" "$bdate" +%s 2>/dev/null || date -d "${bdate//_/-}" +%s 2>/dev/null || echo 0)
    local now=$(date +%s)
    local age=$(( (now - bepoch) / 86400 ))
    
    if [ $age -gt 30 ]; then
        log_warn "[LOW BACKUP AGE] Last backup for $city is $age days old"
    else
        log_info "Last backup for $city is $age days old"
    fi
}

for city in "${CITIES[@]}"; do
    env_file=".env.${city}"
    
    log_info "Starting deployment for city: $city"
    
    # IMPORTANT: DB restore is MANUAL only. Do not auto-restore on deploy.
    # Use ./scripts/restore_db_city.sh --city $city if needed (e.g. after volume wipe with down -v).
    # See "Daily DB Backup & Manual Restore Flow for Multi-City" in README.
    
    log_info "Checking backup age for $city (non-fatal pre-deploy check)..."
    check_backup_age "$city"
    
    if ! ensure_env_file "$city"; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_CITIES+=("$city")
        continue
    fi
    
    log_info "Environment prepared for $city. Deploying with compose..."
    
    # Build env-file args: use .env.prod (common secrets, POSTGRES_PASSWORD, AWS keys, etc.)
    # as base when present, then city-specific file (provides/overrides CITY_MAIN_URL etc.).
    # This allows load_secrets.sh downloads + per-city .env.* to work together.
    # Later --env-file overrides earlier ones.
    ENV_FILE_ARGS=()
    if [[ -f ".env.prod" ]]; then
        ENV_FILE_ARGS+=(--env-file ".env.prod")
    fi
    ENV_FILE_ARGS+=(--env-file "$env_file")
    
    log_info "Deploying $city using ${ENV_FILE_ARGS[*]} (with backup profile) ..."
    
    # Include the "backup" profile so the dedicated per-city backup container
    # (e.g. jurmala-backup-1) is started. The backup service is defined with
    # profiles: ["backup"] in docker-compose.yml.
    # The "curl" debug service is behind profiles: ["debug"] so it is not started.
    PROFILE_ARGS=(--profile backup)
    
    if $COMPOSE_CMD --project-name "$city" "${ENV_FILE_ARGS[@]}" "${PROFILE_ARGS[@]}" up -d; then
        log_info "Successfully deployed $city (including backup container)"
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
