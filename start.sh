#!/bin/sh
set -e

echo "[start] Running alembic migrations..."

# Run alembic upgrade head and capture output
ALEMBIC_OUTPUT=$(alembic upgrade head 2>&1)
ALEMBIC_EXIT=$?

echo "$ALEMBIC_OUTPUT"

if [ $ALEMBIC_EXIT -ne 0 ]; then
    echo "[start] ERROR: alembic upgrade head failed (exit code $ALEMBIC_EXIT)"
    echo "[start] Falling back to startup without migration..."
fi

# Safety check: verify critical columns exist
echo "[start] Verifying critical database columns..."
python3 -c "
import os, sys
sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', '')

from sqlalchemy import create_engine, text, inspect

db_url = os.environ.get('DATABASE_URL', '')
if not db_url:
    try:
        from app.config.settings import DATABASE_URL
        db_url = DATABASE_URL
    except Exception:
        print('[start] WARNING: Cannot determine DATABASE_URL, skipping column check')
        sys.exit(0)

engine = create_engine(db_url)
with engine.connect() as conn:
    inspector = inspect(conn)
    columns = {col['name'] for col in inspector.get_columns('episodes')}

    expected = ['view_mode', 'image_urls', 'comic_view_mode', 'reading_direction']
    missing = [c for c in expected if c not in columns]

    if missing:
        print(f'[start] WARNING: Missing columns: {missing}')
        print('[start] Adding missing columns...')
        with conn.begin():
            col_defs = {
                'view_mode': \"VARCHAR(16) DEFAULT 'text'\",
                'image_urls': \"JSONB DEFAULT '[]'\",
                'comic_view_mode': \"VARCHAR(16) DEFAULT 'paged'\",
                'reading_direction': \"VARCHAR(8) DEFAULT 'ltr'\",
            }
            for col_name in missing:
                sql = f'ALTER TABLE episodes ADD COLUMN {col_name} {col_defs[col_name]}'
                print(f'  -> {sql}')
                conn.execute(text(sql))
        print('[start] Missing columns added successfully.')
    else:
        print('[start] All critical columns present.')
" || echo "[start] WARNING: Column verification script failed (non-fatal)"

# Start uvicorn
# 로그 파일은 app/config/logging.py의 미드나잇 로테이팅 핸들러가 담당하므로
# (일 단위 YYYY-MM-DD.log 자동 생성), 여기서 tee로 중복 기록하지 않는다.
# stdout은 컨테이너 로그(docker compose logs)로 흘러간다.
echo "[start] Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
