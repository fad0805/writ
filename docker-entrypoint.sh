#!/bin/sh
set -e

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head 2>&1 || echo "[entrypoint] Alembic migration failed (continuing)"

echo "[entrypoint] Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
