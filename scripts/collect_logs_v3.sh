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
# PENDING:     Phase 3 (log collection), Phase 4 (artifacts), Phase 5 (DB dump),
#              Phase 6 (state capture), Phase 7 (redaction), Phase 8 (packaging).
#
# Until those land this script validates its inputs, discovers each city's
# containers and lays out the bundle tree, but does not yet copy any log or
# artifact content out of the containers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${REPO_ROOT}/config/cities.yaml"

SCRIPT_VERSION="3.0.0-phase2"

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

# record_status <city> <service> <state> [container]
record_status() {
    printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "${4:--}" >> "$STATUS_FILE"
}

# --- Per-city collection (plan items 2.3, 2.4, 2.5) -------------------------

# collect_city <city> — discovers this city's containers and lays out its
# output tree. Never aborts the run: the caller treats a non-zero return as
# "this city had trouble", and every other city still gets collected (D4).
collect_city() {
    local city="$1"
    local city_dir="${BUNDLE_DIR}/cities/${city}"
    local found=0
    local svc container state

    for svc in "${SERVICE_LIST[@]}"; do
        container="$(find_container "$city" "$svc")"

        if [[ -z "$container" ]]; then
            # Not deployed on this host — a normal state, not an error (2.3).
            record_status "$city" "$svc" "absent" "-"
            continue
        fi

        state="$(container_state "$container")"
        found=$((found + 1))

        # Per-city, per-service directory — no two cities can ever share an
        # output path, whatever their container names are (2.4, fixes D2).
        mkdir -p "${city_dir}/${svc}"
        record_status "$city" "$svc" "$state" "$container"
        log_info "  [$city/$svc] $container ($state)"
    done

    if [[ $found -eq 0 ]]; then
        log_warn "  [$city] no containers found — city not deployed on this host"
        return 0
    fi

    log_info "  [$city] $found container(s) discovered"
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
    printf '%-14s %-8s %-10s %s\n' "CITY" "SERVICE" "STATE" "CONTAINER"
    printf '%-14s %-8s %-10s %s\n' "----" "-------" "-----" "---------"
    while IFS=$'\t' read -r m_city m_svc m_state m_container; do
        printf '%-14s %-8s %-10s %s\n' "$m_city" "$m_svc" "$m_state" "$m_container"
    done < "$STATUS_FILE"
    echo
    echo "NOTE: Phase 2 (discovery) implemented. Log/artifact collection"
    echo "      lands in Phase 3+; see plan_new_collect_logs_v3.md."
} > "$MANIFEST"

log_info "Wrote $MANIFEST"

# --- Summary ----------------------------------------------------------------

# awk (not `grep -vc`, which prints 0 *and* exits 1 on an empty file, so the
# `|| echo 0` fallback would double up).
TOTAL_FOUND=$(awk -F'\t' '$3 != "absent"' "$STATUS_FILE" | wc -l | tr -d ' ')
log_info "Discovery complete: ${TOTAL_FOUND} container(s) across ${#CITIES[@]} city/cities"

log_warn "Phases 1-2 only: containers discovered, but no logs or artifacts"
log_warn "copied yet. Collection lands in Phase 3."

log_info "Done. Bundle at: ${BUNDLE_DIR}"

if [[ ${#TROUBLED_CITIES[@]} -gt 0 ]]; then
    log_warn "Cities with collection trouble: ${TROUBLED_CITIES[*]}"
    exit "$EXIT_PARTIAL"
fi
exit "$EXIT_OK"
