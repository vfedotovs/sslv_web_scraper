#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config/cities.yaml"
LOG_FILE="${SCRIPT_DIR}/../restore_db_city.log"

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
  --city CITY          Restore specific city
  --all                Restore all cities
  --date DATE          Specific date YYYY_MM_DD (default: latest)
  --env ENV            Environment (prod|staging|dev, default: prod)
  --prepare-init       Copy to src/db/ for fresh volume init instead of running restore
  --help               Show help

Examples:
  $0 --city ogre --date 2026_07_08
  $0 --all --prepare-init
EOF
}

CITY=""
ALL=false
DATE=""
ENV="prod"
PREPARE_INIT=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --city) CITY="$2"; shift 2 ;;
        --all) ALL=true; shift ;;
        --date) DATE="$2"; shift 2 ;;
        --env) ENV="$2"; shift 2 ;;
        --prepare-init) PREPARE_INIT=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) log_error "Unknown option $1"; usage; exit 1 ;;
    esac
done

if [[ -z "$CITY" && "$ALL" == false ]]; then
    log_error "Specify --city or --all"
    usage
    exit 1
fi

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
    if [[ "$ALL" == true ]]; then parse_cities "$CONFIG_FILE"; else echo "$CITY"; fi
}

restore_city() {
    local city="$1"
    local env="$2"
    local date_str="$3"

    log_info "Restoring $city (env=$env, date=${date_str:-latest})"

    local env_file=".env.${city}"
    if [[ -f "$env_file" ]]; then
        set -a; source "$env_file"; set +a
    fi

    local container="${city}-db-1"
    local db_user="${DB_USER:-new_docker_user}"
    local db_name="${DB_NAME:-new_docker_db}"
    local password="${POSTGRES_PASSWORD:-}"

    local city_slug="${city//_/-}"
    local bucket="${S3_BUCKET:-sslv-${env}-${city_slug}-db-backups}"

    local key
    if [[ -n "$date_str" ]]; then
        key="db-backups/${date_str//_//}/pg_backup_${date_str}.sql.gz"
    else
        # Get latest
        key=$(aws s3 ls "s3://${bucket}/db-backups/" --recursive | sort | tail -1 | awk '{print $4}')
        if [[ -z "$key" ]]; then
            log_error "No backup found in $bucket"
            return 1
        fi
    fi

    local tmp_dir="/tmp"
    local local_file="${tmp_dir}/$(basename "$key")"
    local sql_file="${local_file%.gz}"

    log_info "Downloading s3://${bucket}/${key} ..."
    aws s3 cp "s3://${bucket}/${key}" "$local_file" --quiet

    log_info "Decompressing..."
    gunzip -f "$local_file"

    if [[ "$PREPARE_INIT" == true ]]; then
        mkdir -p src/db
        cp "$sql_file" "src/db/pg_backup_$(date +%Y_%m_%d).sql"
        log_info "Prepared for init: src/db/pg_backup_....sql"
        rm -f "$sql_file"
        return 0
    fi

    # Restore into running DB
    log_info "Restoring into running container $container ..."
    if [[ -n "$password" ]]; then
        PGPASSWORD="$password" docker exec -i -e PGPASSWORD "$container" \
            psql -U "$db_user" -d "$db_name" < "$sql_file" || {
                log_error "psql restore failed"
                rm -f "$sql_file"
                return 1
            }
    else
        docker exec -i "$container" psql -U "$db_user" -d "$db_name" < "$sql_file" || {
            log_error "psql restore failed"
            rm -f "$sql_file"
            return 1
        }
    fi

    log_info "Restore completed for $city"
    
    # Verification step: list tables (after sample restore)
    log_info "Verification: listing tables (test-restore health check)..."
    if docker exec "$container" psql -U "$db_user" -d "$db_name" -c '\dt+' > /dev/null 2>&1; then
        log_info "Tables listed successfully - DB health OK"
        docker exec "$container" psql -U "$db_user" -d "$db_name" -c '\dt+'
    else
        log_warn "Could not list tables for verification"
    fi
    
    rm -f "$sql_file"
    return 0
}

CITIES=$(get_cities)
SUCCESS=0
FAILED=0

for c in $CITIES; do
    if restore_city "$c" "$ENV" "$DATE"; then
        ((SUCCESS++))
    else
        ((FAILED++))
    fi
done

log_info "Restore summary: Success=$SUCCESS Failed=$FAILED"
[[ $FAILED -gt 0 ]] && exit 1
exit 0
