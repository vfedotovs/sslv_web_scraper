#!/bin/bash
# Send DB comparison logs to ntfy.sh

set -e

WS_CONTAINER=$(docker ps --filter "name=ws-1" --format "{{.Names}}" | head -n 1)
NTFY_TOPIC="ntfy.sh/m5_arm_sslv_alerts"

if [ -z "$WS_CONTAINER" ]; then
    echo "ERROR: WS container not found (looking for *ws-1)"
    exit 1
fi

echo "$(date): Extracting DB comparison logs from $WS_CONTAINER..."

# Extract comparison logs from dbworker.log
MESSAGE=$(docker exec -t "$WS_CONTAINER" grep -i Comparing dbworker.log | \
    awk '{print $1,$2 "COMP:", $8 , "TS hashes:", $14, "DB LTBL hashes" }' | \
    tail -n 3)

if [ -n "$MESSAGE" ]; then
    echo "Sending to ntfy.sh..."
    echo "$MESSAGE" | curl -d @- "$NTFY_TOPIC"
    echo "$(date): DB comparison logs sent successfully"
else
    echo "WARNING: No comparison logs found in dbworker.log"
fi
