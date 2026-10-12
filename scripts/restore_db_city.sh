#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config/cities.yaml"
LOG_FILE="${LOG_FILE:-${SCRIPT_DIR}/../restore_db_city.log}"  # overridable (tests)

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
  --file PATH          Restore a local dump (.sql or .sql.gz) instead of S3; needs --city
                       (e.g. a restore-safety/ copy, to undo a restore)
  --env ENV            Environment (prod|staging|dev, default: prod)
  --bucket BUCKET      Read from this bucket instead of
                       sslv-<env>-<city>-db-backups (rarely needed)
  --prepare-init       Copy to src/db/ for fresh volume init instead of running restore
  --scratch            Test restore: load the dump into a throwaway postgres container,
                       report tables + row counts, then remove it. Never touches the
                       live <city>-db-1 (image: \$RESTORE_TEST_IMAGE, default postgres:15)
  --yes                Skip the confirmation for a restore into the live DB
  --help               Show help

The source bucket comes from --env and the city. .env.<city> is sourced for DB
credentials only: its legacy S3_BUCKET/ENV values (which point at prod) can no
longer redirect the download, and a bucket that does not match --env is refused.

A live restore REPLACES the city's data with the backup: it saves the current
DB to restore-safety/, stops the city's ws/ts/backup containers, drops and
recreates the public schema and loads the dump in ONE transaction (any error
rolls everything back), then restarts the containers. It asks you to type the
city name (or the env for --all) unless --yes is given.

Examples:
  $0 --city ogre --date 2026_07_08
  $0 --all --prepare-init
  $0 --city ogre --env staging --scratch
  $0 --city ogre --file restore-safety/ogre_before_restore_20260919_120000.sql.gz
EOF
}

CITY=""
ALL=false
DATE=""
ENV="prod"
PREPARE_INIT=false
SCRATCH=false
ASSUME_YES=false
FILE=""
BUCKET_OVERRIDE=""
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
        --file) FILE="$2"; shift 2 ;;
        --bucket) BUCKET_OVERRIDE="$2"; shift 2 ;;
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

# The env asked for on the command line. Sourcing .env.<city> below overwrites
# any variable it defines, including ENV, so keep the intended value here.
readonly TARGET_ENV="$ENV"

if [[ -n "$FILE" ]]; then
    if [[ -z "$CITY" || "$ALL" == true ]]; then
        log_error "--file restores one city: use it with --city, not --all"
        exit 1
    fi
    if [[ ! -f "$FILE" ]]; then
        log_error "--file $FILE not found"
        exit 1
    fi
fi

# A live restore replaces the running DB's data: confirm first.
if [[ "$SCRATCH" == false && "$PREPARE_INIT" == false && "$ASSUME_YES" == false ]]; then
    target="${CITY:-$ENV}"
    scope="${CITY:+city $CITY}"
    scope="${scope:-ALL cities (env $ENV)}"
    log_warn "About to restore into the LIVE database of ${scope}."
    log_warn "  Its current data will be REPLACED (a safety copy goes to restore-safety/ first)."
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

# prepare_load_file <sql_file> <server_version_num> [psql command...]
# Sets LOAD_FILE to the file to load: the dump itself, or a filtered copy
# (<sql_file>.load) without the lines the target cannot run. (The log functions
# write to stdout, so the result comes back in LOAD_FILE, not on stdout.)
#  - \restrict / \unrestrict (pg_dump >= 15.14, Aug 2025): dropped when the
#    given psql cannot run them (probed only when a psql command is given).
#  - SET transaction_timeout (pg_dump 17+): dropped when the server is older
#    than 17. PostgreSQL 15 rejects it, so ON_ERROR_STOP loads of every backup
#    taken with the trixie-based backup image failed (B-3 / P-2).
prepare_load_file() {
    local sql_file="$1" server="$2"; shift 2
    local drop=()
    LOAD_FILE="$sql_file"
    if [[ $# -gt 0 ]] && grep -q '^\\restrict ' "$sql_file" \
            && ! printf '\\restrict probe\n\\unrestrict probe\n' | "$@" -q -v ON_ERROR_STOP=1 > /dev/null 2>&1; then
        log_warn "psql predates \\restrict; loading the dump without those lines"
        drop+=('^\\(un)?restrict ')
    fi
    if [[ "$server" =~ ^[0-9]+$ ]] && (( server < 170000 )) \
            && grep -q '^SET transaction_timeout = ' "$sql_file"; then
        log_warn "Dump is from pg_dump 17+ but the server is PostgreSQL $((server / 10000)): dropping SET transaction_timeout"
        drop+=('^SET transaction_timeout = ')
    fi
    if [[ ${#drop[@]} -eq 0 ]]; then
        return 0
    fi
    local pattern
    pattern=$(IFS='|'; echo "${drop[*]}")
    LOAD_FILE="${sql_file}.load"
    if ! grep -v -E "$pattern" "$sql_file" > "$LOAD_FILE"; then
        log_error "Could not write $LOAD_FILE"
        return 1
    fi
}

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

    local psql_cmd=(docker exec -i "$name" psql -X -h 127.0.0.1 -U "$db_user" -d "$db_name")
    local server errors rc=0
    server=$("${psql_cmd[@]}" -t -A -c "SHOW server_version_num" 2>/dev/null | tr -d '[:space:]')
    if ! prepare_load_file "$sql_file" "$server" "${psql_cmd[@]}"; then
        rc=1
    # Load exactly as the live restore does: one transaction, stop at the first
    # error. Counting ERROR lines and only warning let dumps through that the
    # live restore rejects (P-2, docs/staging_signoff_release-2.0.0.md).
    elif ! errors=$("${psql_cmd[@]}" -q -v ON_ERROR_STOP=1 --single-transaction -f - \
            < "$LOAD_FILE" 2>&1 > /dev/null); then
        log_error "Scratch restore FAILED for $city: the dump does not load (psql stopped at the first error)"
        log_error "  $(printf '%s\n' "$errors" | grep -m1 -E 'ERROR|FATAL' || printf '%s\n' "$errors" | tail -1)"
        rc=1
    fi
    if [[ "$LOAD_FILE" != "$sql_file" ]]; then
        rm -f "$LOAD_FILE"
    fi

    if [[ $rc -eq 0 ]]; then
        report_tables "Scratch restore" "$city" "${psql_cmd[@]}" || rc=1
    fi
    docker rm -f "$name" > /dev/null 2>&1 || true
    return $rc
}

# report_tables <label> <city> <psql command...>
# Logs the row count of every public table; fails when there are no tables or
# every table is empty (a restore that "worked" but brought nothing back).
report_tables() {
    local label="$1" city="$2"; shift 2
    local tables total=0 count
    tables=$("$@" -t -A -c \
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1" 2>/dev/null || true)
    if [[ -z "$tables" ]]; then
        log_error "$label FAILED for $city: no tables in the restored DB"
        return 1
    fi
    log_info "Restored tables (row counts):"
    for t in $tables; do
        count=$("$@" -t -A -c "SELECT count(*) FROM \"$t\"" 2>/dev/null || echo 0)
        log_info "  $t: $count"
        total=$((total + count))
    done
    if [[ "$total" -eq 0 ]]; then
        log_error "$label FAILED for $city: tables exist but hold 0 rows"
        return 1
    fi
    log_info "$label OK for $city: $total rows across $(echo "$tables" | wc -w | tr -d ' ') tables"
}

# live_psql / live_pg_dump <container> <user> <db> <password> [args...]
# Run psql / pg_dump inside a city's live DB container.
live_psql() {
    local container="$1" db_user="$2" db_name="$3" password="$4"; shift 4
    if [[ -n "$password" ]]; then
        PGPASSWORD="$password" docker exec -i -e PGPASSWORD "$container" \
            psql -X -U "$db_user" -d "$db_name" "$@"
    else
        docker exec -i "$container" psql -X -U "$db_user" -d "$db_name" "$@"
    fi
}

live_pg_dump() {
    local container="$1" db_user="$2" db_name="$3" password="$4"
    if [[ -n "$password" ]]; then
        PGPASSWORD="$password" docker exec -e PGPASSWORD "$container" pg_dump -U "$db_user" -d "$db_name"
    else
        docker exec "$container" pg_dump -U "$db_user" -d "$db_name"
    fi
}

container_running() {
    [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" == "true" ]]
}

# Replace a city's live data with a plain-SQL dump, atomically.
# Backups taken before dev-1.7.9.9 are plain pg_dump output without DROP
# statements: replayed over existing tables they fail on CREATE TABLE and
# append rows to any table without a unique key. Newer ones use --clean
# --if-exists. Either way: safety dump -> stop writers -> drop + recreate the
# public schema and load the dump in one transaction -> restart writers
# (this also removes objects that are not in the dump).
live_restore() {
    local city="$1" sql_file="$2" db_user="$3" db_name="$4" password="$5"
    local container="${city}-db-1"
    if ! container_running "$container"; then
        log_error "$container is not running; nothing was restored"
        return 1
    fi

    # 1. Safety copy of the current data, so a wrong restore can be undone.
    local safety_dir
    safety_dir="$(cd "${SCRIPT_DIR}/.." && pwd)/restore-safety"
    local safety
    safety="${safety_dir}/${city}_before_restore_$(date +%Y%m%d_%H%M%S).sql.gz"
    mkdir -p "$safety_dir"
    log_info "Saving the current $city DB to $safety ..."
    if ! live_pg_dump "$container" "$db_user" "$db_name" "$password" | gzip > "$safety"; then
        rm -f "$safety"
        log_error "Safety dump failed; nothing was restored"
        return 1
    fi

    # 2. Drop the lines this server or psql cannot run: \restrict from a newer
    #    pg_dump, SET transaction_timeout from pg_dump 17 (prepare_load_file).
    local server load_file
    server=$(live_psql "$container" "$db_user" "$db_name" "$password" -t -A \
        -c "SHOW server_version_num" 2>/dev/null | tr -d '[:space:]')
    if ! prepare_load_file "$sql_file" "$server" live_psql "$container" "$db_user" "$db_name" "$password"; then
        log_error "Could not prepare the dump; nothing was restored"
        return 1
    fi
    load_file="$LOAD_FILE"

    # 3. Stop the city's writers so nothing changes data or holds locks mid-restore.
    local stopped=() svc c
    for svc in ws ts backup; do
        c="${city}-${svc}-1"
        if container_running "$c" && docker stop "$c" > /dev/null; then
            stopped+=("$c")
        fi
    done
    if [[ ${#stopped[@]} -gt 0 ]]; then
        log_info "Stopped during the restore: ${stopped[*]}"
    fi

    # 4. Replace the schema and load the dump as ONE transaction (-1 needs -f;
    #    "-f -" reads stdin). ON_ERROR_STOP aborts on the first error and the
    #    whole transaction, including the DROP SCHEMA, rolls back.
    local rc=0
    log_info "Replacing $city data with the backup (single transaction; any error rolls back) ..."
    { printf 'SET client_min_messages = warning;\nDROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n'; cat "$load_file"; } \
        | live_psql "$container" "$db_user" "$db_name" "$password" \
            -q -v ON_ERROR_STOP=1 --single-transaction -f - > /dev/null || rc=$?
    [[ "$load_file" != "$sql_file" ]] && rm -f "$load_file"

    # 5. Restart whatever was stopped, whether or not the load worked.
    if [[ ${#stopped[@]} -gt 0 ]]; then
        if docker start "${stopped[@]}" > /dev/null; then
            log_info "Restarted: ${stopped[*]}"
        else
            log_error "Could not restart: ${stopped[*]} — start them manually"
        fi
    fi

    if [[ $rc -ne 0 ]]; then
        log_error "Restore FAILED for $city and was rolled back; the live DB is unchanged."
        log_error "  (Safety copy, not needed: $safety)"
        return 1
    fi
    log_info "Restore completed for $city. Undo with:"
    log_info "  ./scripts/restore_db_city.sh --city $city --file $safety"
    report_tables "Live restore" "$city" live_psql "$container" "$db_user" "$db_name" "$password"
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
        # .env.<city> still carries the legacy single-city ENV=prod and
        # S3_BUCKET=sslv-prod-<city>-db-backups. Sourced with `set -a` they
        # overwrote this script's own ENV and would restore a PROD dump into
        # this city's live DB. Take credentials from the file, nothing else.
        if [[ -n "${S3_BUCKET:-}" ]]; then
            log_warn "Ignoring S3_BUCKET=$S3_BUCKET from $env_file (bucket comes from --env)"
            unset S3_BUCKET
        fi
        ENV="$TARGET_ENV"
        env="$TARGET_ENV"
    fi

    local container="${city}-db-1"
    local db_user="${DB_USER:-new_docker_user}"
    local db_name="${DB_NAME:-new_docker_db}"
    local password="${POSTGRES_PASSWORD:-}"

    local city_slug="${city//_/-}"
    local bucket="${BUCKET_OVERRIDE:-sslv-${env}-${city_slug}-db-backups}"

    # Last line of defence: restoring a prod dump into a staging DB (or the
    # reverse) must not be possible by accident.
    if [[ -z "$FILE" && "$bucket" != "sslv-${env}-"* ]]; then
        log_error "Refusing to restore $city from $bucket: not an '${env}' bucket (sslv-${env}-...)"
        return 1
    fi

    # restore_city runs as an `if` condition, where set -e is off: every step
    # that can fail must be checked explicitly.
    local sql_file
    if [[ -n "$FILE" ]]; then
        sql_file="/tmp/restore_${city}_$$.sql"
        log_info "Using local dump $FILE"
        if [[ "$FILE" == *.gz ]]; then
            gunzip -c "$FILE" > "$sql_file" || { log_error "Cannot decompress $FILE"; rm -f "$sql_file"; return 1; }
        else
            cp "$FILE" "$sql_file" || { log_error "Cannot read $FILE"; return 1; }
        fi
    else
        local key
        if [[ -n "$date_str" ]]; then
            # Newest backup of that day. Keys are db-backups/YYYY/MM/DD/
            # pg_backup_YYYYMMDD_HHMMSS.sql.gz; the old pg_backup_YYYY_MM_DD
            # guess never matched one, so --date always failed.
            if ! [[ "$date_str" =~ ^[0-9]{4}_[0-9]{2}_[0-9]{2}$ ]]; then
                log_error "--date must be YYYY_MM_DD, got '$date_str'"
                return 1
            fi
            key=$(aws s3 ls "s3://${bucket}/db-backups/${date_str//_//}/" --recursive | sort | tail -1 | awk '{print $4}')
            if [[ -z "$key" ]]; then
                log_error "No backup for $date_str in s3://${bucket}/db-backups/${date_str//_//}/"
                return 1
            fi
        else
            # Get latest
            key=$(aws s3 ls "s3://${bucket}/db-backups/" --recursive | sort | tail -1 | awk '{print $4}')
            if [[ -z "$key" ]]; then
                log_error "No backup found in $bucket"
                return 1
            fi
        fi

        local local_file
        local_file="/tmp/$(basename "$key")"
        sql_file="${local_file%.gz}"

        log_info "Downloading s3://${bucket}/${key} ..."
        aws s3 cp "s3://${bucket}/${key}" "$local_file" --quiet || { log_error "Download failed"; return 1; }

        log_info "Decompressing..."
        gunzip -f "$local_file" || { log_error "Cannot decompress $local_file"; rm -f "$local_file"; return 1; }
    fi

    if [[ "$SCRATCH" == true ]]; then
        local rc=0
        scratch_restore "$city" "$sql_file" "$db_user" "$db_name" || rc=$?
        rm -f "$sql_file"
        return $rc
    fi

    if [[ "$PREPARE_INIT" == true ]]; then
        # The init scripts run on src/db's image (FROM postgres:<major>) with
        # ON_ERROR_STOP, so drop what that major cannot run.
        local init_major
        init_major=$(sed -n 's/^FROM postgres:\([0-9][0-9]*\).*/\1/p' "${SCRIPT_DIR}/../src/db/Dockerfile" | head -1)
        if ! prepare_load_file "$sql_file" "${init_major:+$((init_major * 10000))}"; then
            rm -f "$sql_file"
            return 1
        fi
        mkdir -p src/db
        cp "$LOAD_FILE" "src/db/pg_backup_$(date +%Y_%m_%d).sql"
        [[ "$LOAD_FILE" != "$sql_file" ]] && rm -f "$LOAD_FILE"
        log_info "Prepared for init: src/db/pg_backup_....sql"
        rm -f "$sql_file"
        return 0
    fi

    local rc=0
    live_restore "$city" "$sql_file" "$db_user" "$db_name" "$password" || rc=$?
    rm -f "$sql_file"
    return $rc
}

CITIES=$(get_cities)
SUCCESS=0
FAILED=0

for c in $CITIES; do
    # Subshell: restore_city sources .env.<city>; keep it from leaking into the next city.
    if (restore_city "$c" "$ENV" "$DATE"); then
        SUCCESS=$((SUCCESS + 1))
    else
        FAILED=$((FAILED + 1))
    fi
done

log_info "Restore summary: Success=$SUCCESS Failed=$FAILED"
[[ $FAILED -gt 0 ]] && exit 1
exit 0
