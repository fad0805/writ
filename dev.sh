#!/bin/bash
set -e

APP_ENV="development"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

VENV_DIR="$ROOT_DIR/venv"
PYTHON="$VENV_DIR/bin/python3"

# Backend setup
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}[setup]${NC} venv 없음 → 생성 중..."
    python3 -m venv "$VENV_DIR"
fi

echo -e "${YELLOW}[setup]${NC} Python 의존성 확인 중..."
"$PYTHON" -m pip install -r "$ROOT_DIR/app/requirements.txt" --quiet

# Frontend setup
if [ -d "$ROOT_DIR/web" ]; then
    echo -e "${YELLOW}[setup]${NC} npm 확인 중..."
    (cd "$ROOT_DIR/web" && npm install --silent)
fi

# ── 포트 충돌 감지 및 대체 포트 할당 ──

_find_port() {
    local base_port=$1
    local port=$base_port
    while ss -tlnH "sport = :$port" 2>/dev/null | grep -q .; do
        ((port++))
    done
    echo "$port"
}

_report_port_conflict() {
    local port=$1
    local label=$2
    local proc_info
    proc_info=$(ss -tlnpH "sport = :$port" 2>/dev/null | head -1 | sed -n 's/.*users:(\([^)]*\)).*/\1/p')
    echo -e "${RED}[port]${NC} 포트 $port($label) 가 이미 사용 중입니다."
    if [ -n "$proc_info" ]; then
        echo -e "${RED}[port]${NC} 사용 중인 프로세스: $proc_info"
    fi
}

BACKEND_PORT=$(_find_port 8000)
if [ "$BACKEND_PORT" != "8000" ]; then
    _report_port_conflict 8000 "backend"
    echo -e "${YELLOW}[port]${NC} 대체 포트: $BACKEND_PORT"
fi

FRONTEND_PORT=3000
if [ -d "$ROOT_DIR/web" ]; then
    FRONTEND_PORT=$(_find_port 3000)
    if [ "$FRONTEND_PORT" != "3000" ]; then
        _report_port_conflict 3000 "frontend"
        echo -e "${YELLOW}[port]${NC} 대체 포트: $FRONTEND_PORT"
    fi
fi

# ── 로그 저장 ──
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_DATE=$(date +%Y-%m-%d)
COMBINED_LOG="$LOG_DIR/$LOG_DATE.log"

# ── 서버 실행 및 오류 감지 ──

PIDS=()
PID_LABELS=()
_CLEANING_UP=0
_cleanup() {
    if [ "$_CLEANING_UP" = "1" ]; then
        return
    fi
    _CLEANING_UP=1
    local i pid label
    for i in "${!PIDS[@]}"; do
        pid="${PIDS[$i]}"
        label="${PID_LABELS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null || true
        fi
        echo -e "${YELLOW}[stop]${NC} $label 종료됨 (PID: $pid)"
    done
    wait 2>/dev/null || true
    echo -e "${GREEN}[done]${NC} 모든 서버가 종료되었습니다."
    exit
}
trap _cleanup EXIT INT TERM

_wait_or_die() {
    local pid=$1 label=$2
    sleep 2
    if ! kill -0 "$pid" 2>/dev/null; then
        wait "$pid" 2>/dev/null || true
        echo -e "${RED}[error]${NC} $label 서버가 시작되지 않았습니다." >&2
        exit 1
    fi
    echo -e "${GREEN}[ready]${NC} $label 서버 실행 중 (PID: $pid)"
}

_prefix_output() {
    local pre=$1 col=$2 line
    while IFS= read -r line; do
        echo -e "${col}${pre}${NC} $line"
    done
}

_prefix_web() {
    local pre=$1 col=$2 line
    while IFS= read -r line; do
        case "$line" in
            *"GET /packs-dev/"*|*"GET /_next/"*|*"GET /favicon.ico"*|*"GET /apple-touch-icon"*)
                continue ;;
        esac
        echo -e "${col}${pre}${NC} $line"
    done
}

echo -e "${YELLOW}[api]${NC} 데이터베이스 마이그레이션 실행 중..."
cd "$ROOT_DIR" && . "$VENV_DIR"/bin/activate && "$PYTHON" -m alembic upgrade head 2>&1 | _prefix_output "[migrate]" "$YELLOW" || true
# 마이그레이션 파일 정리 (5개 초과 시 오래된 것 제거)
MIG_DIR="$ROOT_DIR/alembic/versions"
MIG_COUNT=$(ls -1 "$MIG_DIR"/*.py 2>/dev/null | wc -l)
if [ "$MIG_COUNT" -gt 5 ]; then
    LATEST=$(cd "$ROOT_DIR" && . "$VENV_DIR"/bin/activate && "$PYTHON" -m alembic heads 2>/dev/null | head -1 | awk '{print $1}')
    for f in $(ls -1t "$MIG_DIR"/*.py | tail -n +6); do
        rm "$f"
    done
    echo -e "${YELLOW}[migrate]${NC} 오래된 마이그레이션 $((MIG_COUNT - 5))개 정리 완료"
fi
echo -e "${YELLOW}[api]${NC} 서버 시작 중 (포트 $BACKEND_PORT)..."
cd "$ROOT_DIR" && APP_ENV=development PYTHONUNBUFFERED=1 "$PYTHON" -m uvicorn app.main:app --reload --reload-exclude 'db_data/*' --host 0.0.0.0 --port "$BACKEND_PORT" \
    > >(tee -a "$COMBINED_LOG" | _prefix_output "[api]" "$GREEN") 2>&1 &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")
PID_LABELS+=("api (uvicorn)")
_wait_or_die "$BACKEND_PID" "backend"

FRONTEND_PID=""
if [ -d "$ROOT_DIR/web" ]; then
    echo -e "${YELLOW}[web]${NC} 서버 시작 중 (포트 $FRONTEND_PORT)..."
    (cd "$ROOT_DIR/web" && exec stdbuf -oL npx next dev --port "$FRONTEND_PORT") \
        > >(tee -a "$COMBINED_LOG" | _prefix_web "[web]" "$BLUE") 2>&1 &
    FRONTEND_PID=$!
    PIDS+=("$FRONTEND_PID")
    PID_LABELS+=("web (next)")
    _wait_or_die "$FRONTEND_PID" "frontend"
fi

echo ""
echo -e "${GREEN}[api]${NC} http://localhost:$BACKEND_PORT"
[ -n "$FRONTEND_PID" ] && echo -e "${BLUE}[web]${NC} http://localhost:$FRONTEND_PORT"
echo "[dev] Press Ctrl+C to stop."
echo ""

# Monitor processes — report if one dies
while true; do
    for pid in "${PIDS[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" 2>/dev/null || true
            echo -e "${RED}[error]${NC} 서버 (PID: $pid) 가 종료되었습니다." >&2
            _cleanup
        fi
    done
    sleep 1
done
