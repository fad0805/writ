#!/bin/sh
set -e

# Running as root — create log file with proper ownership
logfile="/app/logs/$(date +%Y-%m-%d).log"
touch "$logfile" 2>/dev/null
chown writ:writ "$logfile" 2>/dev/null || true

# Drop privileges and run the app as the writ user
exec su-exec writ:writ /app/run.sh "$logfile"
