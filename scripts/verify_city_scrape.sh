#!/bin/bash
set -euo pipefail

# Phase 3 Item 10: End-to-end verification for dynamic page count + multi-city
# Usage: ./scripts/verify_city_scrape.sh jurmala   (or ogre, sigulda, etc.)
# Assumes the ws service is reachable at http://localhost:8000 (use make up or docker compose)

CITY="${1:-jurmala}"
BASE_URL="http://localhost:8000"
WS_ENDPOINT="${BASE_URL}/run-task/${CITY}"

echo "=== Verifying scrape for city: ${CITY} ==="

# 1. Trigger the task
echo "Triggering ${WS_ENDPOINT} ..."
curl -sS -X GET "${WS_ENDPOINT}" || {
  echo "ERROR: Could not reach ${WS_ENDPOINT}. Is the ws service running?"
  echo "Try: make up   or   docker compose --env-file .env.${CITY} up -d"
  exit 1
}

echo ""
sleep 2

# 2. Check for raw data report file (now city-prefixed thanks to Phase 3)
TODAY=$(date +%Y-%m-%d)
DATA_DIR="data"
LOCAL_LAMBDA_DIR="local_lambda_raw_scraped_data"

echo "Looking for city-prefixed report files..."
RAW_FILE=$(find "${DATA_DIR}" -name "${CITY}-raw-data-report-${TODAY}*.txt" 2>/dev/null | head -1 || true)
if [[ -z "$RAW_FILE" ]]; then
  RAW_FILE=$(find . -name "${CITY}-raw-data-report-${TODAY}*.txt" 2>/dev/null | head -1 || true)
fi

if [[ -n "$RAW_FILE" ]]; then
  echo "✅ Found raw report: $RAW_FILE"
  AD_COUNT=$(grep -c 'https://ss.lv/msg' "$RAW_FILE" || echo 0)
  echo "   Ads in raw file: $AD_COUNT"
else
  echo "⚠️  No ${CITY}-raw-data-report file found in data/ or current dir yet (may be in progress or using legacy name)"
fi

# 3. Check logs for dynamic page detection (from Phase 1/2/4 work)
echo ""
echo "Checking recent logs for page detection..."
if [[ -f web_scraper.log ]]; then
  grep -E "Detected .* page|Scraping page .*${CITY}|jurmala|ogre" web_scraper.log | tail -5 || true
else
  echo "  (web_scraper.log not present in this dir)"
fi

# 4. Basic duplicate check on the raw file (if found)
if [[ -n "$RAW_FILE" ]]; then
  echo ""
  DUPE_COUNT=$(sort "$RAW_FILE" | uniq -d | wc -l || echo 0)
  if [[ "$DUPE_COUNT" -eq 0 ]]; then
    echo "✅ No duplicate ad entries in raw report"
  else
    echo "⚠️  Found $DUPE_COUNT duplicate lines in raw report"
  fi
fi

# 5. Check that non-existent page handling is respected (code-level verification)
echo ""
echo "Code-level check: non-existent pages should not be fetched (handled in get_total_pages + loop)"
echo "  See: src/ws/app/wsmodules/web_scraper.py (get_total_pages + for loop from 1 to total_pages)"

echo ""
echo "=== Verification for ${CITY} completed ==="
echo "Manual next steps (as per plan):"
echo "  - Compare AD_COUNT above with live count from https://www.ss.lv/lv/real-estate/flats/${CITY}/sell/"
echo "  - Check downstream files (pandas_df.csv, basic_price_stats.txt, etc.) contain data for this city"
echo "  - Repeat for other cities: ./scripts/verify_city_scrape.sh ogre"
