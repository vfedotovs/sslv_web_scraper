#!/bin/bash
#
# Stop and remove every city's containers and networks (config/cities.yaml).
#
# Database volumes (<city>_db_data) are KEPT by default, so a later deploy
# comes back with the same data. To also delete them — all scraped history
# for every city — pass --purge-data; it asks you to type the environment
# name (M6_ENV, default prod) unless --yes is given.
#
# Usage:
#   ./undeploy-multi-city.sh                          # keep data
#   M6_ENV=staging ./undeploy-multi-city.sh --purge-data
#   M6_ENV=staging ./undeploy-multi-city.sh --purge-data --yes   # no prompt (CI)

set -euo pipefail

PURGE_DATA=false
ASSUME_YES=false
for arg in "$@"; do
    case "$arg" in
        --purge-data) PURGE_DATA=true ;;
        --yes) ASSUME_YES=true ;;
        -h|--help) sed -n '3,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown argument: $arg (see --help)" >&2; exit 2 ;;
    esac
done
M6_ENV="${M6_ENV:-prod}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config/cities.yaml"
LOG_FILE="${SCRIPT_DIR}/undeploy-multi-city.log"

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

# Shared cities.yaml parser (provides parse_cities)
source "${SCRIPT_DIR}/scripts/lib/cities.sh"

# Get list of cities (portable, works on macOS bash 3.2+)
CITIES=()
while IFS= read -r city; do
    [[ -n "$city" ]] && CITIES+=("$city")
done < <(parse_cities "$CONFIG_FILE")

if [[ ${#CITIES[@]} -eq 0 ]]; then
    log_error "No cities found in $CONFIG_FILE"
    exit 1
fi

log_info "Found ${#CITIES[@]} cities to undeploy: ${CITIES[*]}"

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

DOWN_ARGS=(down --remove-orphans)
if [[ "$PURGE_DATA" == "true" ]]; then
    log_warn "--purge-data: the database volume of EVERY city will be deleted (env: $M6_ENV)."
    log_warn "  Cities: ${CITIES[*]}"
    if [[ "$ASSUME_YES" != "true" ]]; then
        if [[ ! -t 0 ]]; then
            log_error "--purge-data needs confirmation: run interactively or add --yes"
            exit 1
        fi
        answer=""
        read -r -p "Type the environment name ($M6_ENV) to delete all city data: " answer || true
        if [[ "$answer" != "$M6_ENV" ]]; then
            log_error "Confirmation did not match; nothing was undeployed."
            exit 1
        fi
    fi
    DOWN_ARGS+=(-v)
else
    log_info "Database volumes are kept (pass --purge-data to delete them)."
fi

# Check common files once
if [[ ! -f "docker-compose.yml" ]]; then
    log_error "docker-compose.yml not found in current directory"
    exit 1
fi

SUCCESS_COUNT=0
FAIL_COUNT=0
FAILED_CITIES=()

for city in "${CITIES[@]}"; do
    env_file=".env.${city}"
    
    log_info "Starting undeploy for city: $city"
    
    # Build env-file args only if the file is present on disk.
    # This makes undeploy work without .env.* files needing to exist.
    # --profile backup: older Compose v2 releases skip profiled services on
    # down, which would leave <city>-backup-1 running.
    COMPOSE_ARGS=(--project-name "$city" --profile backup)
    if [[ -f "$env_file" ]]; then
        COMPOSE_ARGS+=(--env-file "$env_file")
    else
        log_warn "No $env_file on disk; proceeding with project-name only (sufficient for down)"
    fi
    
    log_info "Stopping and removing $city ..."
    
    if $COMPOSE_CMD "${COMPOSE_ARGS[@]}" "${DOWN_ARGS[@]}"; then
        log_info "Successfully undeployed $city"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        log_error "Failed to undeploy $city"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_CITIES+=("$city")
    fi
done

echo ""
log_info "Undeploy summary:"
log_info "  Total cities: ${#CITIES[@]}"
log_info "  Successful:   $SUCCESS_COUNT"
log_info "  Failed:       $FAIL_COUNT"

if [[ $FAIL_COUNT -gt 0 ]]; then
    log_error "Failed cities: ${FAILED_CITIES[*]}"
    log_error "Undeploy completed with errors."
    exit 1
else
    log_info "All cities undeployed successfully."
    exit 0
fi
