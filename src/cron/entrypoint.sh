#!/bin/bash
set -e

echo "Starting cron service..."
echo "Current time: $(date)"
echo "Timezone: $TZ"

# Ensure crontab is loaded
echo "Loading crontab..."
cat /etc/crontabs/root

# Verify scripts are executable
echo "Verifying scripts..."
ls -la /scripts/

# Test Docker access (will fail if socket not mounted)
echo "Testing Docker access..."
if docker ps > /dev/null 2>&1; then
    echo "✅ Docker access confirmed"
    docker ps --format "table {{.Names}}\t{{.Status}}"
else
    echo "⚠️  Warning: Cannot access Docker. Make sure /var/run/docker.sock is mounted"
fi

# Test AWS CLI (will show error if credentials not configured)
echo "Testing AWS CLI..."
if aws s3 ls > /dev/null 2>&1; then
    echo "✅ AWS access confirmed"
else
    echo "⚠️  Warning: AWS credentials not configured or no access to S3"
fi

echo "Starting crond in foreground..."
exec "$@"
