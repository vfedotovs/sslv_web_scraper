#!/bin/bash
# Send Docker container stats to ntfy.sh

set -e

NTFY_TOPIC="ntfy.sh/m5_arm_sslv_alerts"

# Get the WS container ID/name
WS_CONTAINER=$(docker ps --filter "name=ws-1" --format "{{.Names}}" | head -n 1)

if [ -z "$WS_CONTAINER" ]; then
    echo "ERROR: WS container not found (looking for *ws-1)"
    exit 1
fi

echo "$(date): Collecting container stats for $WS_CONTAINER..."

# Get stats (container name, CPU%, MEM USAGE / LIMIT, MEM%)
MESSAGE=$(docker stats "$WS_CONTAINER" --no-stream --format "{{.Container}} CPU:{{.CPUPerc}} MEM:{{.MemUsage}} {{.MemPerc}}")

if [ -n "$MESSAGE" ]; then
    echo "Sending to ntfy.sh..."
    echo "$MESSAGE" | curl -d @- "$NTFY_TOPIC"
    echo "$(date): Container stats sent successfully"
else
    echo "WARNING: No stats available"
fi
