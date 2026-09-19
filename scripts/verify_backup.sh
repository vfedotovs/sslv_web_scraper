#!/bin/bash
#
# Read-only check of the newest DB backup per city in S3: age and size.
# Takes no backup, prunes nothing, touches no container.
#
# Usage:
#   ./scripts/verify_backup.sh --city ogre --env staging
#   ./scripts/verify_backup.sh --all --env prod
# Options:
#   --max-age-hours N   newest backup older than this fails (default 26)
#   --min-size-kb N     newest backup smaller than this fails
#                       (default $MIN_BACKUP_SIZE_KB, else 10)
#
# Exit code: 0 when every checked city has a fresh, non-trivial backup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config/cities.yaml"
source "${SCRIPT_DIR}/lib/cities.sh"

CITY=""
ALL=false
ENV="prod"
MAX_AGE_HOURS=26
MIN_SIZE_KB="${MIN_BACKUP_SIZE_KB:-10}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --city) CITY="$2"; shift 2 ;;
        --all) ALL=true; shift ;;
        --env) ENV="$2"; shift 2 ;;
        --max-age-hours) MAX_AGE_HOURS="$2"; shift 2 ;;
        --min-size-kb) MIN_SIZE_KB="$2"; shift 2 ;;
        -h|--help) sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option $1 (see --help)" >&2; exit 2 ;;
    esac
done

if [[ -n "$CITY" ]]; then
    cities="$CITY"
elif [[ "$ALL" == true ]]; then
    cities=$(parse_cities "$CONFIG_FILE")
else
    echo "Specify --city CITY or --all" >&2
    exit 2
fi

# Hours since an S3 LastModified timestamp (ISO 8601); portable across GNU/BSD date.
age_hours() {
    python3 -c 'import sys, datetime as d
t = d.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
print(int((d.datetime.now(d.timezone.utc) - t).total_seconds() // 3600))' "$1"
}

failed=0
printf "%-12s %-7s %-8s %-10s %s\n" "CITY" "RESULT" "AGE" "SIZE" "NEWEST OBJECT"
for city in $cities; do
    bucket="sslv-${ENV}-${city//_/-}-db-backups"
    if ! newest=$(aws s3api list-objects-v2 --bucket "$bucket" --prefix db-backups/ \
            --query 'sort_by(Contents, &LastModified)[-1].[Key, LastModified, Size]' \
            --output text 2>/dev/null); then
        printf "%-12s %-7s %-8s %-10s %s\n" "$city" "FAIL" "-" "-" "cannot list s3://$bucket"
        failed=$((failed + 1)); continue
    fi
    if [[ -z "$newest" || "$newest" == "None" ]]; then
        printf "%-12s %-7s %-8s %-10s %s\n" "$city" "FAIL" "-" "-" "no backups in s3://$bucket"
        failed=$((failed + 1)); continue
    fi
    read -r key last_modified size <<< "$newest"
    age=$(age_hours "$last_modified")
    size_kb=$((size / 1024))
    result="OK"
    reasons=()
    if [[ "$age" -gt "$MAX_AGE_HOURS" ]]; then result="FAIL"; reasons+=("older than ${MAX_AGE_HOURS}h"); fi
    if [[ "$size_kb" -lt "$MIN_SIZE_KB" ]]; then result="FAIL"; reasons+=("smaller than ${MIN_SIZE_KB} KB"); fi
    [[ "$result" == "FAIL" ]] && failed=$((failed + 1))
    note="s3://$bucket/$key"
    if [[ ${#reasons[@]} -gt 0 ]]; then note="$note ($(IFS=';'; echo "${reasons[*]}" | sed 's/;/; /g'))"; fi
    printf "%-12s %-7s %-8s %-10s %s\n" "$city" "$result" "${age}h" "${size_kb} KB" "$note"
done

if [[ "$failed" -gt 0 ]]; then
    echo "$failed city backup(s) failed verification."
    exit 1
fi
echo "All checked backups are fresh and above ${MIN_SIZE_KB} KB."
