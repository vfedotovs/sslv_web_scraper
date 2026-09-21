#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config/cities.yaml"
LOG_FILE="${LOG_FILE:-${SCRIPT_DIR}/../backup_db_city.log}"  # overridable (tests)

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
  --bucket BUCKET      Upload to this bucket instead of
                       sslv-<env>-<city>-db-backups (rarely needed)
  --help               Show this help

The destination is derived from --env and the city. .env.<city> is sourced for
DB credentials only: its legacy S3_BUCKET/ENV values (which point at prod) can
no longer redirect the upload, and a bucket that does not match --env is
refused.

Examples:
  $0 --city salaspils --env staging
  $0 --all --env prod
EOF
}

# Parse args
CITY=""
ALL=false
ENV="prod"
BUCKET_OVERRIDE=""

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
        --bucket)
            BUCKET_OVERRIDE="$2"
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

# The env asked for on the command line. Sourcing .env.<city> below overwrites
# any variable it defines, including ENV, so keep the intended value here.
readonly TARGET_ENV="$ENV"

# Shared cities.yaml parser (provides parse_cities)
source "${SCRIPT_DIR}/lib/cities.sh"

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
        # .env.<city> still carries the legacy single-city values ENV=prod and
        # S3_BUCKET=sslv-prod-<city>-db-backups. Sourced with `set -a` they
        # overwrote this script's own ENV and redirected every upload to the
        # prod bucket, whose retention then pruned real prod backups. Take
        # credentials from the file, nothing else.
        if [[ -n "${S3_BUCKET:-}" ]]; then
            log_warn "Ignoring S3_BUCKET=$S3_BUCKET from $env_file (bucket comes from --env)"
            unset S3_BUCKET
        fi
        ENV="$TARGET_ENV"
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

    # Run pg_dump. --clean --if-exists: the dump drops each object before
    # recreating it, so it restores cleanly over existing tables too.
    # No `docker exec -t`: a TTY merges pg_dump's stderr into the dump file
    # and turns every line ending into CRLF.
    log_info "Running pg_dump for $city ..."
    if ! PGPASSWORD="$password" docker exec -e PGPASSWORD "$container" \
        pg_dump --clean --if-exists -U "$db_user" -d "$db_name" > "$backup_file"; then
        log_error "pg_dump failed for $city"
        rm -f "$backup_file"
        return 1
    fi

    # Gzip
    log_info "Compressing backup..."
    gzip -f "$backup_file"

    # Determine S3 bucket: always from --env + city, never from the env file.
    local city_slug="${city//_/-}"
    local bucket="${BUCKET_OVERRIDE:-sslv-${env}-${city_slug}-db-backups}"

    # Last line of defence: a staging run must never write into a prod bucket
    # (the upload also prunes that bucket to the newest 5 objects).
    if [[ "$bucket" != "sslv-${env}-"* ]]; then
        log_error "Refusing to upload $city to $bucket: not an '${env}' bucket (sslv-${env}-...)"
        rm -f "$gzip_file"
        return 1
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
        
        # Verification: check size and presence in S3 (basic health check)
        log_info "Verifying backup..."
        size=$(stat -c%s "$gzip_file" 2>/dev/null || stat -f%z "$gzip_file" 2>/dev/null || echo 0)
        threshold=1024
        if [ "$size" -lt "$threshold" ]; then
            log_warn "Backup size $size bytes < ${threshold} threshold"
        else
            log_info "Backup size OK: $size bytes"
        fi
        
        if aws s3 ls "s3://${bucket}/${key}" > /dev/null 2>&1; then
            log_info "Verified: backup present in S3"
        else
            log_warn "Backup not found in S3 after upload"
        fi
        
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
        SUCCESS=$((SUCCESS + 1))
    else
        FAILED=$((FAILED + 1))
    fi
done

log_info "Backup summary: Successful=$SUCCESS Failed=$FAILED"
if [[ $FAILED -gt 0 ]]; then
    exit 1
fi
exit 0
