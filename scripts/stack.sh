#!/usr/bin/env bash
# Start or stop the four ReceivableOS services locally (no Docker), for the demo, QA and CI. Owner: PM.
#
#   scripts/stack.sh start    # exports .env, fresh OCR state, starts ports 8001-8003 and 8000, waits for /health
#   scripts/stack.sh stop
#   scripts/stack.sh logs     # tail every service log
#
# ENV_FILE picks another env file (default .env). Logs and state go to STACK_DIR (default .stack/, git-ignored).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK_DIR="${STACK_DIR:-$ROOT/.stack}"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
PYTHON="${PYTHON:-python}"
SERVICES=("ocr-ai 8001" "policy-ai 8002" "agent-wallet 8003" "orchestrator 8000")

start() {
  mkdir -p "$STACK_DIR"
  if [[ -f "$ENV_FILE" ]]; then set -a; source "$ENV_FILE"; set +a; fi
  # OCR remembers every invoice it has seen; a fresh state file makes 01_happy.pdf a first sighting again.
  export OCR_STATE_PATH="${OCR_STATE_PATH:-$STACK_DIR/ocr-state.sqlite}"
  rm -f "$OCR_STATE_PATH" "$OCR_STATE_PATH"-*
  for entry in "${SERVICES[@]}"; do
    read -r name port <<<"$entry"
    "$PYTHON" -m uvicorn app.main:app --app-dir "$ROOT/services/$name" --port "$port" \
      >"$STACK_DIR/$name.log" 2>&1 &
    echo $! >"$STACK_DIR/$name.pid"
  done
  for entry in "${SERVICES[@]}"; do
    read -r name port <<<"$entry"
    for _ in $(seq 1 60); do
      if curl -fs "http://localhost:$port/health" >/dev/null; then echo "$name up on $port"; continue 2; fi
      sleep 1
    done
    echo "$name did not answer /health on $port; last log lines:" >&2
    tail -20 "$STACK_DIR/$name.log" >&2
    exit 1
  done
}

stop() {
  for entry in "${SERVICES[@]}"; do
    read -r name _ <<<"$entry"
    pid_file="$STACK_DIR/$name.pid"
    if [[ -f "$pid_file" ]]; then kill "$(cat "$pid_file")" 2>/dev/null || true; rm -f "$pid_file"; fi
  done
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  logs) tail -n 50 "$STACK_DIR"/*.log ;;
  *) echo "usage: $0 start|stop|restart|logs" >&2; exit 2 ;;
esac
