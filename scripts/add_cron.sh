#!/bin/bash

# M6 Backup/Restore cron helper
# Usage:
#   ./add_cron.sh                    # add default daily backup for all cities (prod)
#   ./add_cron.sh --env staging      # for staging
#   ./add_cron.sh --restore          # example for restore (manual usually)

set -euo pipefail

ENV="prod"
ACTION="backup"

while [[ $# -gt 0 ]]; do
    case $1 in
        --env) ENV="$2"; shift 2 ;;
        --restore) ACTION="restore"; shift ;;
        *) echo "Unknown arg $1"; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup_db_city.sh"
RESTORE_SCRIPT="${SCRIPT_DIR}/restore_db_city.sh"

if [[ "$ACTION" == "backup" ]]; then
    CRON_CMD="${BACKUP_SCRIPT} --all --env ${ENV}"
    CRON_SCHEDULE="0 2 * * *"   # daily 2am
    COMMENT="# M6 daily DB backup (${ENV})"
else
    CRON_CMD="${RESTORE_SCRIPT} --all --env ${ENV}   # manual - edit date as needed"
    CRON_SCHEDULE="0 3 * * 1"   # example Monday
    COMMENT="# M6 weekly restore example (${ENV}) - customize"
fi

echo "Adding cron: $CRON_SCHEDULE $CRON_CMD"
(
    crontab -l 2>/dev/null || true
    echo "$COMMENT"
    echo "$CRON_SCHEDULE $CRON_CMD"
) | crontab -

echo "Cron installed. View with: crontab -l"
echo "Edit with: crontab -e"
