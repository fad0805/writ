#!/bin/sh
mkdir -p /app/logs 2>/dev/null || true

echo 'waiting for api...'
for i in 1 2 3 4 5; do
  wget -q -O- http://api:8000/nodeinfo/2.0 2>/dev/null && break
  echo 'api not ready, retry...'
  sleep 2
done

LOG="/app/logs/$(date +%Y-%m-%d).log"
if ! touch "$LOG" 2>/dev/null; then
  echo "warn: cannot write $LOG, web logs will go to stdout only" >&2
  exec npm start
fi

exec npm start 2>&1 | while IFS= read -r line; do
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$line"
done | tee -a "$LOG"
