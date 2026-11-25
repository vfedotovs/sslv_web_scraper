#!/bin/bash
#
# One-off repair of prices df_cleaner truncated before dev-1.7.9.23: it kept
# only the first two space-separated groups, so "1 130 000 €" was stored as
# 1130. Known ads are never re-fetched, so these rows do not heal on their own.
#
# A row is repaired only when price < 10000 AND sqm * sqm_price is within 2%
# of price * 1000 - the area and per-m2 price were parsed correctly and
# confirm the lost "000". The new price is price * 1000; the last group
# (at most 999 EUR, < 0.1% of a 1M+ price) is not recoverable.
#
# Usage:
#   ./scripts/repair_truncated_prices.sh --city jurmala          # dry run
#   ./scripts/repair_truncated_prices.sh --all --apply           # fix
# Back up first: make backup-city CITY=<city> M6_ENV=<env>
#
# Exit code: 0 ok (dry run or applied), 1 a city's DB could not be queried.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/../config/cities.yaml"
source "${SCRIPT_DIR}/lib/cities.sh"

CITY=""
ALL=false
APPLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --city) CITY="$2"; shift 2 ;;
        --all) ALL=true; shift ;;
        --apply) APPLY=true; shift ;;
        -h|--help) sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

TRUNCATED="price < 10000 AND sqm > 0 AND sqm_price > 0
    AND sqm * sqm_price BETWEEN price * 1000 * 0.98 AND price * 1000 * 1.02"

psql_in() {
    docker exec -i "$1-db-1" psql -U new_docker_user -d new_docker_db -v ON_ERROR_STOP=1 "${@:2}"
}

failed=0
for city in $cities; do
    echo "== $city"
    if ! psql_in "$city" -c "
        SELECT 'listed_ads' AS tbl, url_hash, room_count, price,
               price * 1000 AS repaired, sqm, sqm_price
          FROM listed_ads WHERE $TRUNCATED
        UNION ALL
        SELECT 'removed_ads', url_hash, room_count, price,
               price * 1000, sqm, sqm_price
          FROM removed_ads WHERE $TRUNCATED;"; then
        echo "   could not query ${city}-db-1" >&2
        failed=1
        continue
    fi
    if [[ "$APPLY" == true ]]; then
        psql_in "$city" -c "
            BEGIN;
            UPDATE listed_ads SET price = price * 1000 WHERE $TRUNCATED;
            UPDATE removed_ads SET price = price * 1000 WHERE $TRUNCATED;
            COMMIT;" || { echo "   update failed for $city (rolled back)" >&2; failed=1; }
    fi
done

if [[ "$APPLY" != true ]]; then
    echo
    echo "Dry run: nothing changed. Back up, then re-run with --apply."
fi
exit $failed
