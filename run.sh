#!/bin/sh
set -e

logfile="$1"
alembic upgrade head

if [ -f "$logfile" ] && [ -w "$logfile" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1 | tee -a "$logfile"
else
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
