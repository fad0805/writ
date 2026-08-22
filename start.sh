#!/bin/sh
set -e

echo "[start] Running alembic migrations..."

# set -e 하에서도 실패를 감지할 수 있도록 if 문으로 실행한다.
# 마이그레이션 실패 시 스키마 불일치 상태로 기동하는 것보다 종료가 안전하며,
# compose의 restart: unless-stopped가 재시도한다.
if ! ALEMBIC_OUTPUT=$(alembic upgrade head 2>&1); then
    echo "$ALEMBIC_OUTPUT"
    echo "[start] ERROR: alembic upgrade head failed"
    exit 1
fi
echo "$ALEMBIC_OUTPUT"

# Start uvicorn
# 로그 파일은 app/config/logging.py의 미드나잇 로테이팅 핸들러가 담당하므로
# (일 단위 YYYY-MM-DD.log 자동 생성), 여기서 tee로 중복 기록하지 않는다.
# stdout은 컨테이너 로그(docker compose logs)로 흘러간다.
echo "[start] Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
