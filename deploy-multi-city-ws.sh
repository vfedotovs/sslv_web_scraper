#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config/cities.yaml"
LOG_FILE="${SCRIPT_DIR}/deploy-multi-city.log"

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
# Post-deploy trigger + wait (provides post_deploy_verify)
source "${SCRIPT_DIR}/scripts/lib/post_deploy.sh"

# Get list of cities (portable, works on macOS bash 3.2+)
CITIES=()
while IFS= read -r city; do
    [[ -n "$city" ]] && CITIES+=("$city")
done < <(parse_cities "$CONFIG_FILE")

if [[ ${#CITIES[@]} -eq 0 ]]; then
    log_error "No cities found in $CONFIG_FILE"
    exit 1
fi

log_info "Found ${#CITIES[@]} cities to deploy: ${CITIES[*]}"

# === Fresh Volume / Backup Enforcement ===
# By default this script only warns on missing or old backups (non-fatal).
#
# To FAIL the deploy for any city that has a fresh volume (no backup found):
#   FAIL_ON_FRESH_VOLUME=true ./deploy-multi-city-ws.sh
#
# See the detailed "DB / FRESH VOLUME GUIDANCE" section below for more context.

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

# Check common files once (outside per-city loop)
if [[ ! -f "docker-compose.yml" ]]; then
    log_error "docker-compose.yml not found in current directory"
    exit 1
fi

# All config comes from CICD_FILES_BUCKET: .env.prod + database.ini (common) and
# .env.<city> (per city). The legacy single-city helpers (scripts/load_secrets.sh,
# scripts/set_s3_env_from_aws_sm.sh) are intentionally NOT sourced here: they
# download from the M5 bucket and export shared values that break multi-city deploys.
#
# Compose gives shell env precedence over --env-file when interpolating ${VAR}, so
# clear variables the env files must own. Otherwise a stale or empty export (e.g.
# S3_BUCKET="" from a failed Secrets Manager lookup) silently overrides every city.
unset S3_BUCKET DEST_EMAIL SRC_EMAIL RELEASE_VERSION SENDGRID_API_KEY

# Optional: allow overriding the cicd files bucket
# For M6 staging deployments, default to the dedicated staging CICD bucket
CICD_FILES_BUCKET=${CICD_FILES_BUCKET:-sslv-staging-m6-cicd-files}

# Generic downloader for any file from the CICD bucket.
# Returns 0 on success/present, 1 on failure. Logs info on actions.
# Designed so direct s3 cp works with s3:GetObject only (no ListBucket needed).
# With force=true the file is always re-downloaded, so a stale or foreign copy on
# disk (e.g. left behind by load_secrets.sh from the M5 bucket) is replaced.
# The download goes to a temp file first, so a failed fetch never clobbers a local copy.
_download_cicd_file() {
    local filename="$1"
    local force="${2:-false}"
    if [[ "$force" != "true" && -f "$filename" ]]; then
        log_info "Using existing $filename on disk"
        return 0
    fi

    log_info "Downloading $filename from s3://${CICD_FILES_BUCKET}/ (using IAM)..."
    local tmp="${filename}.download.$$"
    if aws s3 cp "s3://${CICD_FILES_BUCKET}/${filename}" "$tmp" --quiet 2>&1; then
        mv -f "$tmp" "$filename"
        log_info "Downloaded $filename successfully (source: s3://${CICD_FILES_BUCKET}/${filename})"
        if [[ "$filename" == .env* ]]; then
            chmod 600 "$filename" 2>/dev/null || true
        fi
        return 0
    else
        rm -f "$tmp"
        return 1
    fi
}

# Public helper for common artifacts (non-fatal usage). Always fetches a fresh copy.
ensure_cicd_file() {
    if ! _download_cicd_file "$1" true; then
        log_warn "Could not download $1 from s3://${CICD_FILES_BUCKET}/"
        log_warn "  (Check IAM has s3:GetObject on object, file present in bucket, or place locally)"
        return 1
    fi
    return 0
}

# Fetch common files fresh on every deploy (non-fatal; per-city will still enforce its .env.*)
ensure_cicd_file ".env.prod" || log_warn ".env.prod not fetched; falling back to local copy if present (may be stale)"
ensure_cicd_file "database.ini" || log_warn "database.ini not fetched; falling back to local copy if present (may be stale)"

# Ensure database.ini is present in the ws build context.
# src/ws/Dockerfile does: COPY database.ini /
if [[ -f "database.ini" ]]; then
    mkdir -p src/ws
    if ! cmp -s database.ini src/ws/database.ini 2>/dev/null; then
        cp -f database.ini src/ws/database.ini
        log_info "Copied database.ini into src/ws/ for Docker build context"
    fi
fi

# Ensure per-city .env file exists on disk.
# Downloads from S3 (CICD_FILES_BUCKET) using AWS IAM credentials if missing.
# This allows the script to work on fresh hosts without .env.* pre-existing on disk.
# No secrets are printed or leaked by this logic.
ensure_env_file() {
    local city="$1"
    local env_file=".env.${city}"

    if _download_cicd_file "$env_file"; then
        return 0
    fi

    log_error "Failed to download $env_file from s3://${CICD_FILES_BUCKET}/"
    log_error "Check: file exists in bucket, AWS credentials/IAM role has s3:GetObject, and aws cli is configured."
    return 1
}

SUCCESS_COUNT=0
FAIL_COUNT=0
FAILED_CITIES=()

# Pre-deploy safety check for backup age (non-fatal warning only)
# This also helps detect "fresh volume" situations (no backup = likely empty DB after deploy).
# Note: Restore is MANUAL. Use ./scripts/restore_db_city.sh if needed.
check_backup_age() {
    local city="$1"
    local env="${M6_ENV:-prod}"
    local city_slug="${city//_/-}"
    local bucket="sslv-${env}-${city_slug}-db-backups"
    
    local latest=$(aws s3 ls "s3://${bucket}/db-backups/" --recursive 2>/dev/null | sort | tail -1 | awk '{print $1}')
    if [ -z "$latest" ]; then
        log_warn "[FRESH VOLUME] No backup found for $city in $bucket"
        log_warn "  This looks like a fresh/empty volume for $city."
        log_warn "  Tables will be created (empty) by src/db/init.sql on first start."
        log_warn "  If you need historical data, run restore BEFORE or AFTER this deploy:"
        log_warn "    ./scripts/restore_db_city.sh --city $city"
        return 1   # Indicate fresh volume
    fi
    
    # Extract date from path like db-backups/2026/07/09/...
    local bdate=$(echo "$latest" | cut -d/ -f1-3 | tr / _ )
    if [ -z "$bdate" ]; then
        log_warn "[LOW BACKUP] Could not parse backup date for $city"
        return
    fi
    
    local bepoch=$(date -j -f "%Y_%m_%d" "$bdate" +%s 2>/dev/null || date -d "${bdate//_/-}" +%s 2>/dev/null || echo 0)
    local now=$(date +%s)
    local age=$(( (now - bepoch) / 86400 ))
    
    if [ $age -gt 30 ]; then
        log_warn "[LOW BACKUP AGE] Last backup for $city is $age days old"
    else
        log_info "Last backup for $city is $age days old"
    fi
    return 0
}

for city in "${CITIES[@]}"; do
    env_file=".env.${city}"
    
    log_info "Starting deployment for city: $city"
    
    # === DB / FRESH VOLUME GUIDANCE ===
    # DB restore is MANUAL ONLY — this script does NOT restore data.
    #
    # Fresh volume situations (common after first deploy or volume wipe):
    #   - New city volume (never had data)
    #   - After `docker compose --project-name $city down -v`
    #   - Volume was removed or this is a new host
    #
    # What happens on a fresh volume:
    #   - DB starts empty.
    #   - src/db/init.sql (CREATE TABLE IF NOT EXISTS) creates the tables
    #     (listed_ads + removed_ads) automatically.
    #   - No historical data — only data from this point forward will be collected.
    #
    # Recommended order when volume is fresh:
    #   1. (Optional) Restore data first if you have a backup:
    #      ./scripts/restore_db_city.sh --city $city [--prepare-init]
    #   2. Deploy:
    #      ./deploy-multi-city-ws.sh
    #
    # To make this script FAIL the entire deploy for any city that has a fresh volume:
    #   FAIL_ON_FRESH_VOLUME=true ./deploy-multi-city-ws.sh
    #
    # See:
    #   - README.md → "Daily DB Backup & Manual Restore Flow for Multi-City"
    #   - docs/M6_phase_1_backup_restore_service_plan.md
    #   - scripts/restore_db_city.sh --help
    
    log_info "Checking backup age for $city (non-fatal pre-deploy check)..."
    if ! check_backup_age "$city"; then
        if [[ "${FAIL_ON_FRESH_VOLUME:-false}" =~ ^(true|1|yes)$ ]]; then
            log_error "FRESH VOLUME detected for $city and FAIL_ON_FRESH_VOLUME is set."
            log_error "Aborting deployment for this city (as requested by flag)."
            FAIL_COUNT=$((FAIL_COUNT + 1))
            FAILED_CITIES+=("$city")
            continue
        fi
    fi
    
    if ! ensure_env_file "$city"; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_CITIES+=("$city")
        continue
    fi
    
    log_info "Environment prepared for $city. Deploying with compose..."
    
    # Build env-file args: use .env.prod (common secrets, POSTGRES_PASSWORD, AWS keys, etc.)
    # as base when present, then city-specific file (provides/overrides CITY_MAIN_URL etc.).
    # Both come from CICD_FILES_BUCKET (see ensure_cicd_file / ensure_env_file above).
    # Later --env-file overrides earlier ones.
    ENV_FILE_ARGS=()
    if [[ -f ".env.prod" ]]; then
        ENV_FILE_ARGS+=(--env-file ".env.prod")
    fi
    ENV_FILE_ARGS+=(--env-file "$env_file")
    
    log_info "Deploying $city using ${ENV_FILE_ARGS[*]} (with backup profile) ..."
    
    # Include the "backup" profile so the dedicated per-city backup container
    # (e.g. jurmala-backup-1) is started. The backup service is defined with
    # profiles: ["backup"] in docker-compose.yml.
    #
    # Note: The old "curl" debug one-shot trigger is no longer used.
    # The immediate post-deploy trigger runs below via post_deploy_verify
    # (scripts/lib/post_deploy.sh), from inside the city's ws container.
    PROFILE_ARGS=(--profile backup)

    # --build: without it compose reuses any existing sslv-ws/ts/backup image,
    # so code changes (e.g. src/backup-svc/backup.py) never reach a host that
    # already has the images. Unchanged images are rebuilt from cache quickly.
    if $COMPOSE_CMD --project-name "$city" "${ENV_FILE_ARGS[@]}" "${PROFILE_ARGS[@]}" up -d --build; then
        log_info "Successfully deployed $city (including backup container)"

        # Immediate post-deploy trigger: run the pipeline now instead of waiting
        # for the 00:40 schedule, and fail the city if the run fails.
        # POST_DEPLOY_VERIFY=false skips it (e.g. redeploying during the nightly run).
        if [[ "${POST_DEPLOY_VERIFY:-true}" =~ ^(false|0|no)$ ]]; then
            log_warn "[$city] Post-deploy verification skipped (POST_DEPLOY_VERIFY=${POST_DEPLOY_VERIFY})"
            SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
            continue
        fi

        log_info "Triggering immediate /run-task/${city} and waiting for the run (timeout ${POST_DEPLOY_VERIFY_TIMEOUT:-1200}s)..."
        verify_rc=0
        # shellcheck disable=SC2086  # COMPOSE_CMD may be two words ("docker compose")
        verify_msg=$(post_deploy_verify "$city" $COMPOSE_CMD --project-name "$city" "${ENV_FILE_ARGS[@]}") || verify_rc=$?
        case "$verify_rc" in
            "$PDV_OK")
                log_info "[$city] Post-deploy verification OK: $verify_msg"
                SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
                ;;
            "$PDV_SKIPPED")
                log_warn "[$city] Post-deploy verification $verify_msg"
                SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
                ;;
            "$PDV_TIMEOUT")
                log_error "[$city] Post-deploy verification timed out: $verify_msg"
                log_error "  The run may still finish; check: $COMPOSE_CMD --project-name $city exec ws python -c \"import urllib.request; print(urllib.request.urlopen('http://localhost:8000/status').read().decode())\""
                log_error "  A fresh volume fetches every ad; raise POST_DEPLOY_VERIFY_TIMEOUT if that is expected."
                FAIL_COUNT=$((FAIL_COUNT + 1))
                FAILED_CITIES+=("$city")
                ;;
            "$PDV_FAILED")
                log_error "[$city] Post-deploy run FAILED: $verify_msg"
                FAIL_COUNT=$((FAIL_COUNT + 1))
                FAILED_CITIES+=("$city")
                ;;
            *)
                log_error "[$city] Post-deploy verification could not run (exit $verify_rc): $verify_msg"
                FAIL_COUNT=$((FAIL_COUNT + 1))
                FAILED_CITIES+=("$city")
                ;;
        esac
    else
        log_error "Failed to deploy $city"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_CITIES+=("$city")
    fi
done

echo ""
log_info "Deployment summary:"
log_info "  Total cities: ${#CITIES[@]}"
log_info "  Successful:   $SUCCESS_COUNT"
log_info "  Failed:       $FAIL_COUNT"

if [[ $FAIL_COUNT -gt 0 ]]; then
    log_error "Failed cities: ${FAILED_CITIES[*]}"
    log_error "Deployment completed with errors."
    exit 1
else
    log_info "All cities deployed successfully."
    exit 0
fi
