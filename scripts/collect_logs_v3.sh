#!/usr/bin/env bash
#
# collect_logs_v3.sh — multi-city aware log & artifact collector.
#
# Replaces collect_logs_v2.sh, which was written for the single-city era and
# is unusable under the current multi-city deployment (it matches every city's
# containers at once and collects them all into one CWD).
#
# See plan_new_collect_logs_v3.md for the full design and phase breakdown.
#
# IMPLEMENTED: Phase 1 — foundation (CLI, logging, preflight, bundle scaffold).
#              Phase 2 — label-based container discovery + MANIFEST status table.
#              Phase 3 — log file + docker logs collection.
# PENDING:     Phase 4 (artifacts), Phase 5 (DB dump), Phase 6 (state capture),
#              Phase 7 (redaction), Phase 8 (packaging).
#
# The script discovers each city's containers and collects their log files and
# docker logs into a per-city bundle tree. Pipeline artifacts (CSV/TXT), DB
# dumps, host/container state, secret redaction and the tar.gz are still to
# come — until Phase 7 lands, treat a bundle as unredacted and do not share it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${REPO_ROOT}/config/cities.yaml"

SCRIPT_VERSION="3.0.0-phase3"

# Exit codes (plan item 8.4)
EXIT_OK=0        # everything requested was collected
EXIT_PARTIAL=1   # some cities/services could not be collected
EXIT_FATAL=2     # preflight or usage failure — nothing was collected

# Shared cities.yaml parser (provides parse_cities)
source "${SCRIPT_DIR}/lib/cities.sh"

# --- Logging (plan item 1.2) ------------------------------------------------
# Format matches deploy-multi-city-ws.sh. Tees into the bundle's collect.log
# once the bundle directory exists; before that, stdout only.

BUNDLE_LOG=""

log() {
    local level="$1"
    shift
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local line="[$timestamp] [$level] $*"
    if [[ -n "$BUNDLE_LOG" ]]; then
        echo "$line" | tee -a "$BUNDLE_LOG"
    else
        echo "$line"
    fi
}

log_info() { log "INFO" "$@"; }
log_warn() { log "WARN" "$@"; }
log_error() { log "ERROR" "$@"; }

# --- Defaults ---------------------------------------------------------------
# Defined before usage() so the help text can quote them.

DEFAULT_SINCE="72h"
DEFAULT_OUTPUT_DIR="${REPO_ROOT}/log-bundles"
VALID_SERVICES="ws ts db backup"

REQUESTED_CITIES=()
COLLECT_ALL=false
RUNNING_ONLY=false
SERVICES="ws,ts,db,backup"
SINCE="$DEFAULT_SINCE"
WITH_DB_DUMP=false
WITH_DATA_DIRS=false
REDACT=true
OUTPUT_DIR="$DEFAULT_OUTPUT_DIR"
ARCHIVE=true

# --- Usage (plan item 1.4) --------------------------------------------------

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Collects logs, artifacts and container state from the multi-city deployment
into a single timestamped bundle, one isolated directory per city.

Options:
  --city CITY          Collect one city (repeatable). Default: all cities.
  --all                Collect every city in config/cities.yaml (default)
  --running-only       Only cities that currently have containers up
  --services LIST      Comma-separated: ws,ts,db,backup (default: all)
  --since DURATION     docker logs time window (default: ${DEFAULT_SINCE})
  --with-db-dump       Include a pg_dump per city (default: off)
  --with-data-dirs     Include /data + /local_lambda_raw_scraped_data
                       (default: off — these grow without bound)
  --no-redact          Skip secret scrubbing (default: redaction ON)
  --output-dir DIR     Destination root (default: ${DEFAULT_OUTPUT_DIR})
  --no-archive         Leave the bundle unpacked, skip the tar.gz
  -h, --help           Show this help

Examples:
  $0                                   # every city, logs only
  $0 --city jurmala --city ogre        # two cities
  $0 --running-only --since 24h        # whatever is up, last 24h
  $0 --city ogre --with-db-dump        # include a debug DB dump

Note: --with-db-dump produces a DEBUG dump only; it is not uploaded to S3.
For real backups use scripts/backup_db_city.sh, and to restore use
scripts/restore_db_city.sh.

Exit codes: ${EXIT_OK}=complete, ${EXIT_PARTIAL}=partial, ${EXIT_FATAL}=fatal (nothing collected)
EOF
}

# --- Helpers ----------------------------------------------------------------

# in_list <needle> <space-separated haystack>
in_list() {
    local needle="$1"
    local item
    for item in $2; do
        [[ "$item" == "$needle" ]] && return 0
    done
    return 1
}

# require_value <flag> <value> — guards flags that take an argument, so that
# "--city --all" fails loudly instead of swallowing the next flag.
require_value() {
    if [[ -z "${2:-}" || "${2:-}" == -* ]]; then
        log_error "Option $1 requires a value"
        usage
        exit "$EXIT_FATAL"
    fi
}

# --- Container discovery (plan items 2.1, 2.2) ------------------------------
#
# Containers are matched on the compose labels, never on a name substring.
# deploy-multi-city-ws.sh runs `compose --project-name <city>`, so
# com.docker.compose.project is the city and com.docker.compose.service is one
# of ws/ts/db/backup. Substring matching on "ws" would hit all six cities at
# once — the root defect of collect_logs_v2.sh (D1/D3).

# find_container <city> <service> — echoes the container name, empty if none.
# Uses `docker ps -a` deliberately: a stopped or crashed container is exactly
# the one whose logs are worth having.
find_container() {
    local city="$1"
    local service="$2"
    docker ps -a \
        --filter "label=com.docker.compose.project=${city}" \
        --filter "label=com.docker.compose.service=${service}" \
        --format '{{.Names}}' 2>/dev/null | head -n1
}

# container_state <container> — running | exited | created | paused | dead | unknown
container_state() {
    docker inspect --format '{{.State.Status}}' "$1" 2>/dev/null || echo "unknown"
}

# discover_running_projects — distinct compose project names with a running
# container. Used to narrow the city list under --running-only (item 2.2).
discover_running_projects() {
    docker ps \
        --filter "label=com.docker.compose.project" \
        --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null \
        | sort -u
}

# --- Log inventory (plan items 3.1, 3.4, 3.5) -------------------------------
#
# Paths verified against the source. src/ws/Dockerfile sets no WORKDIR, so the
# ws logs land in "/"; src/ts/Dockerfile uses /app; the backup service writes
# to /var/log.
#
# The globs end in .log* so RotatingFileHandler's .log.1 … .log.9 rotations
# come along too — v2 collected only the live .log (item 3.2).

WS_LOG_DIR="/"
WS_LOG_GLOB="*.log*"

# Explicit ws log names, used only for the stopped-container fallback below
# (docker cp cannot glob). aws_mailer.log is the one v2 missed while still
# collecting the retired sendgrid_mailer.log (C1); alert_mailer.py writes here
# too. sendgrid_mailer.log is kept as best-effort legacy.
WS_LOGS="ws_main.log web_scraper.log raw_data_report_formatter.log \
dataframe_sanitizer.log dbworker.log analytics.log aws_mailer.log \
s3_file_downloader.log sendgrid_mailer.log"

TS_LOG_DIR="/app"
TS_LOG_GLOB="*.log*"
TS_LOGS="task_scheduler.log"

# The backup service is absent from v2 entirely (C2), yet backup.log is the
# only record of whether the nightly per-city DB backup actually ran.
BACKUP_LOG_DIR="/var/log"
BACKUP_LOG_GLOB="backup.log* cron.log"
BACKUP_LOGS="backup.log cron.log"

# db (postgres) keeps no log files inside the container — everything goes to
# stdout, so it is covered by collect_stdout() alone.

# Cap on docker logs, so one long-running stack cannot balloon the bundle (3.7)
DOCKER_LOG_TAIL=50000

# --- Log collection (plan items 3.2, 3.3, 3.6) ------------------------------

# collect_stdout <container> <dest_dir> — docker logs to stdout.log.
# This is the ONLY place uvicorn tracebacks, container crash output and
# Postgres startup errors appear; none of it is ever written to a file inside
# the container (C5). Works on stopped containers too.
collect_stdout() {
    local container="$1"
    local dest="$2"
    # Container stderr and stdout are interleaved into one file, as emitted.
    if docker logs --since "$SINCE" --timestamps --tail "$DOCKER_LOG_TAIL" \
        "$container" > "${dest}/stdout.log" 2>&1; then
        return 0
    fi
    return 1
}

# copy_logs <container> <dir_in_container> <glob> <dest_dir>
#   0 = files collected, 2 = nothing matched, 1 = error
#
# One streamed tar per service rather than v2's per-file `docker cp` loop:
# a single exec, globs handled container-side, and missing files cause no
# noise (item 3.3, fixes D8).
#
# The container-side program is POSIX sh, never bash — python:3.8-slim-buster
# and the postgres images are not guaranteed to have bash. It filters the glob
# down to entries that actually exist, so a partial match (e.g. backup.log
# present but cron.log absent) still produces a valid archive.
copy_logs() {
    local container="$1"
    local src_dir="$2"
    local glob="$3"
    local dest="$4"
    local tmp_tar rc=0

    tmp_tar="$(mktemp "${TMPDIR:-/tmp}/sslv-collect.XXXXXX")"

    docker exec "$container" sh -c "
        cd '${src_dir}' 2>/dev/null || exit 0
        list=''
        for f in ${glob}; do
            [ -e \"\$f\" ] && list=\"\$list \$f\"
        done
        [ -n \"\$list\" ] || exit 0
        tar cf - \$list 2>/dev/null
    " > "$tmp_tar" 2>/dev/null || rc=$?

    # Decide on the archive itself rather than the exit status: tar can warn
    # about a vanished file mid-stream yet still produce a usable archive.
    if [[ ! -s "$tmp_tar" ]]; then
        rm -f "$tmp_tar"
        return 2
    fi

    mkdir -p "$dest"
    if ! tar xf "$tmp_tar" -C "$dest" 2>/dev/null; then
        rm -f "$tmp_tar"
        return 1
    fi

    rm -f "$tmp_tar"
    return 0
}

# copy_logs_stopped <container> <dir_in_container> <names> <dest_dir>
#   0 = files collected, 2 = nothing matched, 1 = error
#
# docker exec needs a running container, but docker cp does not. For an exited
# or crashed container — exactly the case `docker ps -a` was used for in
# Phase 2 — fall back to copying the known log names one by one. Rotations
# cannot be recovered this way, since docker cp has no globbing.
copy_logs_stopped() {
    local container="$1"
    local src_dir="$2"
    local names="$3"
    local dest="$4"
    local name copied=0

    mkdir -p "$dest"
    for name in $names; do
        if docker cp "${container}:${src_dir%/}/${name}" "${dest}/${name}" \
            >/dev/null 2>&1; then
            copied=$((copied + 1))
        fi
    done

    [[ $copied -eq 0 ]] && return 2
    return 0
}

# count_files <dir> — number of regular files collected under dir
count_files() {
    [[ -d "$1" ]] || { echo 0; return 0; }
    find "$1" -type f | wc -l | tr -d ' '
}

# collect_service_logs <service> <container> <state> <dest_dir>
# Routes a service to its log directory/glob and picks the running vs stopped
# strategy. Echoes a short detail string for the MANIFEST; returns 1 on error.
collect_service_logs() {
    local service="$1"
    local container="$2"
    local state="$3"
    local dest="$4"
    local log_dir glob names rc detail

    case "$service" in
        ws)     log_dir="$WS_LOG_DIR";     glob="$WS_LOG_GLOB";     names="$WS_LOGS" ;;
        ts)     log_dir="$TS_LOG_DIR";     glob="$TS_LOG_GLOB";     names="$TS_LOGS" ;;
        backup) log_dir="$BACKUP_LOG_DIR"; glob="$BACKUP_LOG_GLOB"; names="$BACKUP_LOGS" ;;
        db)     echo "stdout only (postgres logs to stdout)"; return 0 ;;
        *)      echo "no log inventory"; return 0 ;;
    esac

    rc=0
    if [[ "$state" == "running" ]]; then
        copy_logs "$container" "$log_dir" "$glob" "${dest}/logs" || rc=$?
    else
        copy_logs_stopped "$container" "$log_dir" "$names" "${dest}/logs" || rc=$?
    fi

    case "$rc" in
        0)
            detail="logs=$(count_files "${dest}/logs")"
            [[ "$state" != "running" ]] && detail="${detail} (no rotations: container ${state})"
            echo "$detail"
            return 0
            ;;
        2)
            echo "logs=0 (none present)"
            return 0
            ;;
        *)
            echo "logs=ERROR"
            return 1
            ;;
    esac
}

# --- Argument parsing (plan item 1.4) ---------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --city)
            require_value "$1" "${2:-}"
            REQUESTED_CITIES+=("$2")
            shift 2
            ;;
        --all)
            COLLECT_ALL=true
            shift
            ;;
        --running-only)
            RUNNING_ONLY=true
            shift
            ;;
        --services)
            require_value "$1" "${2:-}"
            SERVICES="$2"
            shift 2
            ;;
        --since)
            require_value "$1" "${2:-}"
            SINCE="$2"
            shift 2
            ;;
        --with-db-dump)
            WITH_DB_DUMP=true
            shift
            ;;
        --with-data-dirs)
            WITH_DATA_DIRS=true
            shift
            ;;
        --no-redact)
            REDACT=false
            shift
            ;;
        --output-dir)
            require_value "$1" "${2:-}"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --no-archive)
            ARCHIVE=false
            shift
            ;;
        -h|--help)
            usage
            exit "$EXIT_OK"
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit "$EXIT_FATAL"
            ;;
    esac
done

# --- Argument validation ----------------------------------------------------

if [[ "$COLLECT_ALL" == true && ${#REQUESTED_CITIES[@]} -gt 0 ]]; then
    log_error "--all and --city are mutually exclusive"
    exit "$EXIT_FATAL"
fi

# Validate --services against the known compose service names.
# Commas to spaces, then rely on default IFS word splitting (bash 3.2 safe).
SERVICE_LIST=()
for svc in ${SERVICES//,/ }; do
    if ! in_list "$svc" "$VALID_SERVICES"; then
        log_error "Unknown service '$svc' (valid: ${VALID_SERVICES// /, })"
        exit "$EXIT_FATAL"
    fi
    in_list "$svc" "${SERVICE_LIST[*]:-}" || SERVICE_LIST+=("$svc")
done

if [[ ${#SERVICE_LIST[@]} -eq 0 ]]; then
    log_error "--services resolved to an empty list"
    exit "$EXIT_FATAL"
fi

if [[ -z "$SINCE" ]]; then
    log_error "--since must not be empty"
    exit "$EXIT_FATAL"
fi

if [[ "$REDACT" == false ]]; then
    log_warn "==================================================================="
    log_warn "REDACTION DISABLED — the bundle will contain AWS keys and DB"
    log_warn "passwords in plaintext. Do not attach it to a ticket or share it."
    log_warn "==================================================================="
fi

# --- Preflight (plan item 1.6) ----------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
    log_error "docker not found in PATH"
    exit "$EXIT_FATAL"
fi

if ! docker info >/dev/null 2>&1; then
    log_error "Cannot talk to the Docker daemon (is it running? do you have permission?)"
    exit "$EXIT_FATAL"
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    log_error "Cities configuration file not found: $CONFIG_FILE"
    exit "$EXIT_FATAL"
fi

# Detect docker compose command (plan item 1.5, mirrors deploy-multi-city-ws.sh)
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    log_error "Neither 'docker compose' nor 'docker-compose' found"
    exit "$EXIT_FATAL"
fi

if ! mkdir -p "$OUTPUT_DIR" 2>/dev/null; then
    log_error "Cannot create output directory: $OUTPUT_DIR"
    exit "$EXIT_FATAL"
fi

if [[ ! -w "$OUTPUT_DIR" ]]; then
    log_error "Output directory is not writable: $OUTPUT_DIR"
    exit "$EXIT_FATAL"
fi

# --- Resolve the city list --------------------------------------------------

ALL_CITIES=()
while IFS= read -r _city; do
    [[ -n "$_city" ]] && ALL_CITIES+=("$_city")
done < <(parse_cities "$CONFIG_FILE")

if [[ ${#ALL_CITIES[@]} -eq 0 ]]; then
    log_error "No cities found in $CONFIG_FILE"
    exit "$EXIT_FATAL"
fi

CITIES=()
if [[ ${#REQUESTED_CITIES[@]} -eq 0 ]]; then
    CITIES=("${ALL_CITIES[@]}")
else
    for _city in "${REQUESTED_CITIES[@]}"; do
        if ! in_list "$_city" "${ALL_CITIES[*]}"; then
            log_error "Unknown city '$_city' (known: ${ALL_CITIES[*]})"
            exit "$EXIT_FATAL"
        fi
        # De-duplicate repeated --city flags.
        if ! in_list "$_city" "${CITIES[*]:-}"; then
            CITIES+=("$_city")
        fi
    done
fi

# --running-only: keep just the cities that currently have something up
# (plan item 2.2). Applied after validation so a typo still errors out.
if [[ "$RUNNING_ONLY" == true ]]; then
    RUNNING_PROJECTS="$(discover_running_projects | tr '\n' ' ')"
    log_info "Running compose projects: ${RUNNING_PROJECTS:-<none>}"

    _filtered=()
    for _city in "${CITIES[@]}"; do
        if in_list "$_city" "$RUNNING_PROJECTS"; then
            _filtered+=("$_city")
        else
            log_info "Skipping $_city — no running containers (--running-only)"
        fi
    done

    if [[ ${#_filtered[@]} -eq 0 ]]; then
        log_error "--running-only: none of the requested cities have running containers"
        log_error "Requested: ${CITIES[*]}"
        exit "$EXIT_FATAL"
    fi
    CITIES=("${_filtered[@]}")
fi

# --- Bundle scaffold --------------------------------------------------------

TIMESTAMP="$(date -u '+%Y-%m-%dT%H-%M-%SZ')"
BUNDLE_NAME="sslv-logs-${TIMESTAMP}"
BUNDLE_DIR="${OUTPUT_DIR}/${BUNDLE_NAME}"

mkdir -p "${BUNDLE_DIR}/host" "${BUNDLE_DIR}/cities"

# From here on, log() also tees into the bundle.
BUNDLE_LOG="${BUNDLE_DIR}/collect.log"

log_info "collect_logs_v3.sh ${SCRIPT_VERSION} starting"
log_info "Bundle: ${BUNDLE_DIR}"
log_info "Compose command: ${COMPOSE_CMD}"
log_info "Cities (${#CITIES[@]}): ${CITIES[*]}"
log_info "Services: ${SERVICE_LIST[*]}"
log_info "Options: since=${SINCE} running_only=${RUNNING_ONLY} db_dump=${WITH_DB_DUMP} data_dirs=${WITH_DATA_DIRS} redact=${REDACT} archive=${ARCHIVE}"

# Discovery results, one TSV row per (city, service). Kept on disk rather than
# in an associative array so this stays bash 3.2 (macOS) compatible, and so
# later phases can append to the same record.
STATUS_FILE="${BUNDLE_DIR}/.status.tsv"
: > "$STATUS_FILE"

# record_status <city> <service> <state> [container] [detail]
record_status() {
    printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "${4:--}" "${5:-}" >> "$STATUS_FILE"
}

# --- Per-city collection (plan items 2.3, 2.4, 2.5) -------------------------

# collect_city <city> — discovers this city's containers and lays out its
# output tree. Never aborts the run: the caller treats a non-zero return as
# "this city had trouble", and every other city still gets collected (D4).
collect_city() {
    local city="$1"
    local city_dir="${BUNDLE_DIR}/cities/${city}"
    local found=0 failures=0
    local svc container state svc_dir detail stdout_note

    for svc in "${SERVICE_LIST[@]}"; do
        container="$(find_container "$city" "$svc")"

        if [[ -z "$container" ]]; then
            # Not deployed on this host — a normal state, not an error (2.3).
            record_status "$city" "$svc" "absent" "-" "not deployed"
            continue
        fi

        state="$(container_state "$container")"
        found=$((found + 1))

        # Per-city, per-service directory — no two cities can ever share an
        # output path, whatever their container names are (2.4, fixes D2).
        svc_dir="${city_dir}/${svc}"
        mkdir -p "$svc_dir"

        # stdout/stderr first: it works even on a crashed container (3.6)
        stdout_note="stdout=ok"
        if ! collect_stdout "$container" "$svc_dir"; then
            stdout_note="stdout=ERROR"
            failures=$((failures + 1))
        fi

        # then the on-disk log files (3.1-3.5)
        if ! detail="$(collect_service_logs "$svc" "$container" "$state" "$svc_dir")"; then
            failures=$((failures + 1))
        fi

        record_status "$city" "$svc" "$state" "$container" "${detail}, ${stdout_note}"
        log_info "  [$city/$svc] $container ($state) — ${detail}, ${stdout_note}"
    done

    if [[ $found -eq 0 ]]; then
        log_warn "  [$city] no containers found — city not deployed on this host"
        return 0
    fi

    log_info "  [$city] $found container(s), $(count_files "$city_dir") file(s) collected"
    [[ $failures -gt 0 ]] && return 1
    return 0
}

DISCOVERED_CITIES=0
TROUBLED_CITIES=()

for _city in "${CITIES[@]}"; do
    log_info "Discovering containers for $_city ..."
    # Failure isolation (2.5): one broken city must never abort the run.
    if collect_city "$_city"; then
        DISCOVERED_CITIES=$((DISCOVERED_CITIES + 1))
    else
        log_warn "Collection failed for $_city — continuing with the remaining cities"
        TROUBLED_CITIES+=("$_city")
    fi
done

# --- MANIFEST (discovery section; completed in Phase 8.1) -------------------

MANIFEST="${BUNDLE_DIR}/MANIFEST.txt"
{
    echo "SS.LV multi-city log bundle"
    echo "=========================================================="
    echo "Generated : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Host      : $(hostname)"
    echo "Script    : collect_logs_v3.sh ${SCRIPT_VERSION}"
    echo "Bundle    : ${BUNDLE_NAME}"
    if [[ "$REDACT" == true ]]; then
        echo "Redaction : ON (not yet implemented — Phase 7)"
    else
        echo "Redaction : DISABLED by --no-redact"
    fi
    echo
    echo "Options   : since=${SINCE} running_only=${RUNNING_ONLY}"
    echo "            db_dump=${WITH_DB_DUMP} data_dirs=${WITH_DATA_DIRS}"
    echo "            archive=${ARCHIVE} services=${SERVICE_LIST[*]}"
    echo
    echo "Container discovery"
    echo "----------------------------------------------------------"
    echo "Matched on compose labels com.docker.compose.project=<city>"
    echo "and com.docker.compose.service=<service>. 'absent' means the"
    echo "city/service is not deployed on this host — not an error."
    echo
    printf '%-14s %-8s %-10s %-18s %s\n' "CITY" "SERVICE" "STATE" "CONTAINER" "COLLECTED"
    printf '%-14s %-8s %-10s %-18s %s\n' "----" "-------" "-----" "---------" "---------"
    while IFS=$'\t' read -r m_city m_svc m_state m_container m_detail; do
        printf '%-14s %-8s %-10s %-18s %s\n' \
            "$m_city" "$m_svc" "$m_state" "$m_container" "$m_detail"
    done < "$STATUS_FILE"
    echo
    echo "Log sources"
    echo "----------------------------------------------------------"
    echo "  ws     ${WS_LOG_DIR}${WS_LOG_GLOB} (incl. .log.1-.9 rotations)"
    echo "  ts     ${TS_LOG_DIR}/${TS_LOG_GLOB}"
    echo "  backup ${BACKUP_LOG_DIR}/{backup.log*,cron.log}"
    echo "  db     stdout only (postgres does not log to a file)"
    echo "  all    stdout.log = docker logs --since ${SINCE} --tail ${DOCKER_LOG_TAIL}"
    echo
    echo "Stopped containers fall back to docker cp of the known log names;"
    echo "rotations cannot be recovered from a container that is not running."
    echo
    echo "NOTE: Phases 2-3 implemented (discovery + log collection). Artifacts,"
    echo "      DB dump, state capture, redaction and packaging land in"
    echo "      Phases 4-8; see plan_new_collect_logs_v3.md."
} > "$MANIFEST"

log_info "Wrote $MANIFEST"

# --- Summary ----------------------------------------------------------------

# awk (not `grep -vc`, which prints 0 *and* exits 1 on an empty file, so the
# `|| echo 0` fallback would double up).
TOTAL_FOUND=$(awk -F'\t' '$3 != "absent"' "$STATUS_FILE" | wc -l | tr -d ' ')
TOTAL_FILES=$(count_files "${BUNDLE_DIR}/cities")
BUNDLE_SIZE=$(du -sh "$BUNDLE_DIR" 2>/dev/null | awk '{print $1}')
log_info "Collected ${TOTAL_FILES} file(s) from ${TOTAL_FOUND} container(s) across ${#CITIES[@]} city/cities (${BUNDLE_SIZE:-?})"

log_warn "Phases 1-3 only: logs collected. Artifacts, DB dump, host/container"
log_warn "state, redaction and the tar.gz archive land in Phases 4-8."

log_info "Done. Bundle at: ${BUNDLE_DIR}"

if [[ ${#TROUBLED_CITIES[@]} -gt 0 ]]; then
    log_warn "Cities with collection trouble: ${TROUBLED_CITIES[*]}"
    exit "$EXIT_PARTIAL"
fi
exit "$EXIT_OK"
