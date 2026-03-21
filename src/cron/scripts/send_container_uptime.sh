#!/bin/bash
# Send Docker container uptime information to ntfy.sh

set -e

NTFY_TOPIC="ntfy.sh/m5_arm_sslv_alerts"

echo "$(date): Collecting container uptime information..."

# Extract uptime from docker ps
MESSAGE=$(docker ps | awk -F 'Up' '{print $2}' | awk '{print "UP:", $1 ,$2, $NF}')

if [ -n "$MESSAGE" ]; then
    echo "Sending to ntfy.sh..."
    echo "$MESSAGE" | curl -d @- "$NTFY_TOPIC"
    echo "$(date): Container uptime sent successfully"
else
    echo "WARNING: No uptime information available"
fi
