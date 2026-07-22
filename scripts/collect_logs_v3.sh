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
# PENDING:     Phase 2 (container discovery), Phase 3 (log collection),
#              Phase 4 (artifacts), Phase 5 (DB dump), Phase 6 (state capture),
#              Phase 7 (redaction), Phase 8 (packaging).
#
# Until those land this script validates its inputs and lays out the bundle
# tree, but does not yet copy anything out of the containers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${REPO_ROOT}/config/cities.yaml"

SCRIPT_VERSION="3.0.0-phase1"

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

for _city in "${CITIES[@]}"; do
    # Per-city isolation — no two cities ever share an output path (fixes D2).
    mkdir -p "${BUNDLE_DIR}/cities/${_city}"
done
log_info "Created per-city output directories under ${BUNDLE_DIR}/cities/"

# --- Collection (Phases 2-8, not yet implemented) ---------------------------

log_warn "Phase 1 (foundation) only: no logs, artifacts or state collected yet."
log_warn "Container discovery and collection land in Phases 2-3."
log_warn "See plan_new_collect_logs_v3.md; use scripts/collect_logs_v2.sh"
log_warn "for single-city hosts until then."

log_info "Done. Bundle scaffold at: ${BUNDLE_DIR}"
exit "$EXIT_OK"
