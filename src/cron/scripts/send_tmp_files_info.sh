#!/bin/bash
# Send /tmp file information to ntfy.sh

set -e

NTFY_TOPIC="ntfy.sh/m5_arm_sslv_alerts"

echo "$(date): Collecting /tmp file information..."

# List recent backup files in /tmp
MESSAGE=$(ls -lh /tmp/pg_backup_*.sql 2>/dev/null | \
    awk '{print $6, $7, $8, $5, $9}' | \
    tail -n 5)

if [ -n "$MESSAGE" ]; then
    echo "Sending to ntfy.sh..."
    echo "Recent backups in /tmp:" | curl -d @- "$NTFY_TOPIC"
    echo "$MESSAGE" | curl -d @- "$NTFY_TOPIC"
    echo "$(date): Tmp files info sent successfully"
else
    echo "WARNING: No backup files found in /tmp"
    echo "No backup files found" | curl -d @- "$NTFY_TOPIC"
fi
