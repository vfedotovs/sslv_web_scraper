#!/usr/bin/env bash
# scripts/lib/cities.sh — shared config/cities.yaml parsing.
#
# Single source of truth for turning cities.yaml into a list of city keys.
# Previously this awk program was copy-pasted into four scripts
# (deploy-multi-city-ws.sh, undeploy-multi-city.sh, scripts/backup_db_city.sh,
# scripts/restore_db_city.sh), each having drifted slightly. Sourced, not
# executed.
#
# Usage:
#   source "${SCRIPT_DIR}/lib/cities.sh"
#   while IFS= read -r city; do ... done < <(parse_cities "$CONFIG_FILE")

# Guard against double-sourcing.
if [[ -n "${_SSLV_CITIES_LIB_LOADED:-}" ]]; then
    return 0
fi
_SSLV_CITIES_LIB_LOADED=1

# parse_cities <yaml_file>
#
# Emits one city key per line — the top-level keys nested directly under the
# "cities:" section of config/cities.yaml. Returns 1 if the file is missing.
#
# IMPORTANT: the awk program copies each line into a variable instead of
# modifying $1/$0. Modifying an awk field forces a rebuild of $0 using OFS,
# which can falsely trigger the "stop on next top-level key" rule on the very
# first city — the root cause of the historical "only 1 city found" bug.
parse_cities() {
    local yaml_file="$1"
    if [[ ! -f "$yaml_file" ]]; then
        echo ""
        return 1
    fi

    awk '
        /^cities:/ { in_cities=1; next }
        in_cities && /^[[:space:]]{2}[a-zA-Z0-9_]+:/ {
            city = $0
            gsub(/^[[:space:]]+/, "", city)
            sub(/:.*/, "", city)
            if (city != "") print city
        }
        # Stop when we hit a new top-level key (line does not start with whitespace)
        in_cities && /^[^[:space:]][a-zA-Z_]/ && !/^cities:/ { exit }
    ' "$yaml_file"
}
