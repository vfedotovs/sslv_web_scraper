#!/bin/bash
# Send DB worker results to ntfy.sh

set -e

WS_CONTAINER=$(docker ps --filter "name=ws-1" --format "{{.Names}}" | head -n 1)
NTFY_TOPIC="ntfy.sh/m5_arm_sslv_alerts"

if [ -z "$WS_CONTAINER" ]; then
    echo "ERROR: WS container not found (looking for *ws-1)"
    exit 1
fi

echo "$(date): Extracting DB worker results from $WS_CONTAINER..."

# Extract results from dbworker.log
MESSAGE=$(docker exec -t "$WS_CONTAINER" grep -i result dbworker.log | \
    awk '{print $1,$2 , "N:" $8, "L:", $10 , "To RM:" $12 }' | \
    tail -n 3)

if [ -n "$MESSAGE" ]; then
    echo "Sending to ntfy.sh..."
    echo "$MESSAGE" | curl -d @- "$NTFY_TOPIC"
    echo "$(date): DB worker results sent successfully"
else
    echo "WARNING: No results found in dbworker.log"
fi
