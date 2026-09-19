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
  --scratch            Test restore: load the dump into a throwaway postgres container,
                       report tables + row counts, then remove it. Never touches the
                       live <city>-db-1 (image: \$RESTORE_TEST_IMAGE, default postgres:15)
  --yes                Skip the confirmation for a restore into the live DB
  --help               Show help

A restore into the live DB loads the dump on top of the existing data, so it
asks you to type the city name (or the env for --all) unless --yes is given.

Examples:
  $0 --city ogre --date 2026_07_08
  $0 --all --prepare-init
  $0 --city ogre --env staging --scratch
EOF
}

CITY=""
ALL=false
DATE=""
ENV="prod"
PREPARE_INIT=false
SCRATCH=false
ASSUME_YES=false
RESTORE_TEST_IMAGE="${RESTORE_TEST_IMAGE:-postgres:15}"  # matches src/db/Dockerfile

while [[ $# -gt 0 ]]; do
    case $1 in
        --city) CITY="$2"; shift 2 ;;
        --all) ALL=true; shift ;;
        --date) DATE="$2"; shift 2 ;;
        --env) ENV="$2"; shift 2 ;;
        --prepare-init) PREPARE_INIT=true; shift ;;
        --scratch) SCRATCH=true; shift ;;
        --yes) ASSUME_YES=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) log_error "Unknown option $1"; usage; exit 1 ;;
    esac
done

if [[ -z "$CITY" && "$ALL" == false ]]; then
    log_error "Specify --city or --all"
    usage
    exit 1
fi

# Shared cities.yaml parser (provides parse_cities)
source "${SCRIPT_DIR}/lib/cities.sh"

if [[ "$SCRATCH" == true && "$PREPARE_INIT" == true ]]; then
    log_error "--scratch and --prepare-init are mutually exclusive"
    exit 1
fi

# A live restore replays the dump into the running DB: confirm first.
if [[ "$SCRATCH" == false && "$PREPARE_INIT" == false && "$ASSUME_YES" == false ]]; then
    target="${CITY:-$ENV}"
    scope="${CITY:+city $CITY}"
    scope="${scope:-ALL cities (env $ENV)}"
    log_warn "About to restore into the LIVE database of ${scope}."
    log_warn "  Test first without touching it: add --scratch (make test-restore)."
    if [[ ! -t 0 ]]; then
        log_error "Live restore needs confirmation: run interactively or add --yes"
        exit 1
    fi
    answer=""
    read -r -p "Type '$target' to restore into the live DB: " answer || true
    if [[ "$answer" != "$target" ]]; then
        log_error "Confirmation did not match; nothing was restored."
        exit 1
    fi
fi

# Load a plain-SQL dump into a throwaway postgres container and report what
# came back. Proves the backup restores without touching the live DB.
scratch_restore() {
    local city="$1" sql_file="$2" db_user="$3" db_name="$4"
    local name="sslv-restore-test-${city//_/-}-$$"
    log_info "Scratch restore: starting $RESTORE_TEST_IMAGE as $name ..."
    if ! docker run -d --rm --name "$name" -e POSTGRES_USER="$db_user" \
            -e POSTGRES_PASSWORD=scratch -e POSTGRES_DB="$db_name" \
            "$RESTORE_TEST_IMAGE" > /dev/null; then
        log_error "Could not start $RESTORE_TEST_IMAGE"
        return 1
    fi
    local ready=false
    for _ in $(seq 1 60); do
        # The image restarts postgres once after init; wait for the final server.
        if docker exec "$name" pg_isready -U "$db_user" -d "$db_name" -h 127.0.0.1 > /dev/null 2>&1; then
            ready=true; break
        fi
        sleep 1
    done
    if [[ "$ready" != true ]]; then
        log_error "Scratch postgres did not become ready"
        docker rm -f "$name" > /dev/null 2>&1 || true
        return 1
    fi

    local errors rc=0
    errors=$(docker exec -i "$name" psql -q -h 127.0.0.1 -U "$db_user" -d "$db_name" \
        < "$sql_file" 2>&1 > /dev/null | grep -c 'ERROR' || true)
    [[ "$errors" -gt 0 ]] && log_warn "psql reported $errors error(s) while loading the dump"

    local tables
    tables=$(docker exec "$name" psql -h 127.0.0.1 -U "$db_user" -d "$db_name" -t -A -c \
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1" 2>/dev/null || true)
    local total=0 count
    if [[ -z "$tables" ]]; then
        log_error "Scratch restore FAILED for $city: no tables in the restored DB"
        rc=1
    else
        log_info "Restored tables (row counts):"
        for t in $tables; do
            count=$(docker exec "$name" psql -h 127.0.0.1 -U "$db_user" -d "$db_name" -t -A -c \
                "SELECT count(*) FROM \"$t\"" 2>/dev/null || echo 0)
            log_info "  $t: $count"
            total=$((total + count))
        done
        if [[ "$total" -eq 0 ]]; then
            log_error "Scratch restore FAILED for $city: tables exist but hold 0 rows"
            rc=1
        else
            log_info "Scratch restore OK for $city: $total rows across $(echo "$tables" | wc -w | tr -d ' ') tables"
        fi
    fi
    docker rm -f "$name" > /dev/null 2>&1 || true
    return $rc
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

    if [[ "$SCRATCH" == true ]]; then
        local rc=0
        scratch_restore "$city" "$sql_file" "$db_user" "$db_name" || rc=$?
        rm -f "$sql_file"
        return $rc
    fi

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
        SUCCESS=$((SUCCESS + 1))
    else
        FAILED=$((FAILED + 1))
    fi
done

log_info "Restore summary: Success=$SUCCESS Failed=$FAILED"
[[ $FAILED -gt 0 ]] && exit 1
exit 0
