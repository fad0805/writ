#!/bin/sh
set -e

alembic upgrade head 2>/dev/null || true

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
