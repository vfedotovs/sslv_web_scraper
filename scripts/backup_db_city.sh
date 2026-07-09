#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config/cities.yaml"
LOG_FILE="${SCRIPT_DIR}/../backup_db_city.log"

# Logging
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

log_info() { log "INFO" "$@"; }
log_error() { log "ERROR" "$@"; }
log_warn() { log "WARN" "$@"; }

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Options:
  --city CITY          Backup specific city (e.g. salaspils, ogre)
  --all                Backup all cities from config/cities.yaml
  --env ENV            Environment (prod|staging|dev, default: prod)
  --help               Show this help

Examples:
  $0 --city salaspils --env staging
  $0 --all --env prod
EOF
}

# Parse args
CITY=""
ALL=false
ENV="prod"

while [[ $# -gt 0 ]]; do
    case $1 in
        --city)
            CITY="$2"
            shift 2
            ;;
        --all)
            ALL=true
            shift
            ;;
        --env)
            ENV="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ -z "$CITY" && "$ALL" == false ]]; then
    log_error "Either --city or --all is required"
    usage
    exit 1
fi

# Parse cities from yaml (robust parser)
parse_cities() {
    local yaml_file="$1"
    awk '
        /^cities:/ { in_cities=1; next }
        in_cities && /^[[:space:]]{2}[a-zA-Z0-9_]+:/ {
            city = $0
            gsub(/^[[:space:]]+/, "", city)
            sub(/:.*/, "", city)
            if (city != "") print city
        }
        in_cities && /^[^[:space:]][a-zA-Z_]/ && !/^cities:/ { exit }
    ' "$yaml_file"
}

get_cities() {
    if [[ "$ALL" == true ]]; then
        parse_cities "$CONFIG_FILE"
    else
        echo "$CITY"
    fi
}

# Main backup function for one city
backup_city() {
    local city="$1"
    local env="$2"

    log_info "Starting backup for city: $city (env: $env)"

    # Source per-city env for credentials (POSTGRES_PASSWORD etc.)
    local env_file=".env.${city}"
    if [[ -f "$env_file" ]]; then
        set -a
        # shellcheck source=/dev/null
        source "$env_file"
        set +a
        log_info "Sourced $env_file for credentials"
    else
        log_warn "No $env_file found; relying on environment variables"
    fi

    # Container name based on project
    local container="${city}-db-1"
    local db_user="${DB_USER:-new_docker_user}"
    local db_name="${DB_NAME:-new_docker_db}"
    local password="${POSTGRES_PASSWORD:-}"

    if [[ -z "$password" ]]; then
        log_error "POSTGRES_PASSWORD not set for $city"
        return 1
    fi

    # Prepare backup file
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_dir="/tmp"
    local backup_file="${backup_dir}/pg_backup_${timestamp}.sql"
    local gzip_file="${backup_file}.gz"

    # Run pg_dump
    log_info "Running pg_dump for $city ..."
    if ! PGPASSWORD="$password" docker exec -e PGPASSWORD -t "$container" \
        pg_dump -U "$db_user" -d "$db_name" > "$backup_file"; then
        log_error "pg_dump failed for $city"
        rm -f "$backup_file"
        return 1
    fi

    # Gzip
    log_info "Compressing backup..."
    gzip -f "$backup_file"

    # Determine S3 bucket
    local bucket="${S3_BUCKET:-}"
    if [[ -z "$bucket" ]]; then
        local city_slug="${city//_/-}"
        bucket="sslv-${env}-${city_slug}-db-backups"
    fi

    # S3 key
    local year month day
    year=$(date +%Y)
    month=$(date +%m)
    day=$(date +%d)
    local key="db-backups/${year}/${month}/${day}/pg_backup_${timestamp}.sql.gz"

    # Upload
    log_info "Uploading to s3://${bucket}/${key} ..."
    if aws s3 cp "$gzip_file" "s3://${bucket}/${key}" --quiet; then
        log_info "Successfully uploaded backup for $city"
        
        # Retention: keep last 5 backups in S3 (prune older ones)
        local keep_last=5
        aws s3 ls "s3://${bucket}/db-backups/" --recursive | sort | head -n -${keep_last} | awk '{print $4}' | while read -r old_key; do
            if [ -n "$old_key" ]; then
                aws s3 rm "s3://${bucket}/${old_key}" --quiet
                log_info "Pruned old backup key: $old_key (kept last $keep_last)"
            fi
        done
        
        # Clean up local
        rm -f "$gzip_file"
        return 0
    else
        log_error "Failed to upload backup for $city"
        return 1
    fi
}

# Main
CITIES=$(get_cities)
SUCCESS=0
FAILED=0

for city in $CITIES; do
    if backup_city "$city" "$ENV"; then
        ((SUCCESS++))
    else
        ((FAILED++))
    fi
done

log_info "Backup summary: Successful=$SUCCESS Failed=$FAILED"
if [[ $FAILED -gt 0 ]]; then
    exit 1
fi
exit 0
