#!/bin/sh
# Wrapper invoked by cron (see cronfile).
#
# Restores the container environment captured by entrypoint.sh before running
# backup.py. Arguments are passed through, so the same wrapper serves both the
# nightly backup and the --staleness-check run.
if [ -f /app/container.env ]; then
    . /app/container.env
else
    echo "backup-svc: WARNING /app/container.env missing -" \
         "cron job will run without the container environment" >&2
fi

exec /usr/local/bin/python -u /app/backup.py "$@"
