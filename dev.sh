#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

"$ROOT_DIR/.venv/bin/python3" -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 2>&1 | awk -v pre="[backend]" -v col="\033[0;32m" -v nc="\033[0m" '{print col pre nc " " $0}' &
BACKEND_PID=$!

(cd "$ROOT_DIR/web" && npx next dev 2>&1 | awk -v pre="[frontend]" -v col="\033[0;34m" -v nc="\033[0m" '{print col pre nc " " $0}') &
FRONTEND_PID=$!

trap 'kill '$BACKEND_PID' '$FRONTEND_PID' 2>/dev/null; wait; exit' EXIT INT TERM

echo -e "${GREEN}[backend]${NC} http://localhost:8000"
echo -e "${BLUE}[frontend]${NC} http://localhost:3000"
echo "[dev] Press Ctrl+C to stop."
wait
