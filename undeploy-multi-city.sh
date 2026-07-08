#!/bin/bash

set -euo pipefail

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

# Parse city names from YAML
# Extracts top-level keys directly under the 'cities:' section.
parse_cities() {
    local yaml_file="$1"
    if [[ ! -f "$yaml_file" ]]; then
        echo ""
        return 1
    fi

    # Pure bash parser for this simple YAML structure (2-space indent)
    awk '
        /^cities:/ { in_cities=1; next }
        in_cities && /^[[:space:]]{2}[a-zA-Z0-9_]+:/ {
            gsub(/:/, "", $1)
            gsub(/^[[:space:]]+/, "", $1)
            print $1
        }
        in_cities && /^[a-zA-Z_]/ && !/^cities:/ { exit }
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

SUCCESS_COUNT=0
FAIL_COUNT=0
FAILED_CITIES=()

for city in "${CITIES[@]}"; do
    env_file=".env.${city}"
    
    log_info "Starting undeploy for city: $city"
    
    # For undeploy we are more lenient with missing .env,
    # but we still prefer to have it for consistency.
    if [[ ! -f "$env_file" ]]; then
        log_warn "Environment file not found for city '$city': $env_file (continuing anyway)"
    fi
    
    if [[ ! -f "docker-compose.yml" ]]; then
        log_error "docker-compose.yml not found in current directory"
        exit 1
    fi
    
    log_info "Stopping and removing $city using $env_file ..."
    
    if $COMPOSE_CMD --project-name "$city" --env-file "$env_file" down -v; then
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
