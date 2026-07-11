#!/bin/bash
# Start (or stop) the backend + frontend.
#
#   ./run.sh              start BOTH locally (default)          → all-local mode
#   ./run.sh backend      start only the backend (e.g. on the rented VM)
#   ./run.sh frontend     start only the frontend (e.g. on the laptop)
#   ./run.sh stop         stop whatever this script started here
#   ./run.sh logs         tail the logs
#
# Two deployment shapes:
#   • All local     — ./run.sh on the laptop.
#   • FE→remote BE  — backend on the VM (./run.sh backend), tunnel it back
#       ssh -p <PORT> -L 8000:localhost:8000 root@<HOST>
#     then ./run.sh frontend on the laptop (VITE_API_URL defaults to
#     http://localhost:8000, i.e. the tunnel). No CORS change needed.
#     Exposing the backend directly instead? set VITE_API_URL=http://<host>:<port>
#     here and CORS_ORIGINS=http://localhost:5173 in backend/.env on the VM.
#
# Backend settings come from backend/.env if present (see vast_setup.sh), or
# exported env vars, e.g. locally on macOS:
#   export TOTALSPINESEG_BIN=/Users/kienha/totalspineseg/venv/bin/totalspineseg
#   export SEG_DEVICE=cpu
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$REPO_DIR/.run"
mkdir -p "$RUN_DIR"
BE_PID="$RUN_DIR/backend.pid"; BE_LOG="$RUN_DIR/backend.log"
FE_PID="$RUN_DIR/frontend.pid"; FE_LOG="$RUN_DIR/frontend.log"
HOST="${HOST:-127.0.0.1}"; PORT="${PORT:-8000}"

free_port() {  # $1=port — kill whatever still LISTENs on it (lsof|fuser|ss)
  [ -z "$1" ] && return 0
  local held=""
  if command -v lsof >/dev/null 2>&1; then
    held=$(lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true)
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k "$1"/tcp 2>/dev/null || true; return 0
  elif command -v ss >/dev/null 2>&1; then
    held=$(ss -ltnpH "sport = :$1" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
  fi
  [ -n "$held" ] && kill $held 2>/dev/null || true
}

stop_one() {  # $1=pidfile $2=name $3=port $4=process-pattern
  if [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; then
    kill "$(cat "$1")" 2>/dev/null || true
    echo "stopped $2 (pid $(cat "$1"))"
  fi
  rm -f "$1"
  free_port "$3"
  # Last resort (no lsof/fuser/ss, or orphaned children): pattern kill.
  [ -n "$4" ] && pkill -f "$4" 2>/dev/null || true
}

MODE="${1:-both}"
case "$MODE" in
  stop)
    # ./run.sh stop [backend|frontend]  — no target stops both.
    case "${2:-}" in
      backend)  stop_one "$BE_PID" backend "$PORT" "uvicorn app.main" ;;
      frontend) stop_one "$FE_PID" frontend 5173 "vite" ;;
      "")       stop_one "$BE_PID" backend "$PORT" "uvicorn app.main"; stop_one "$FE_PID" frontend 5173 "vite" ;;
      *) echo "Usage: $0 stop [backend|frontend]"; exit 1 ;;
    esac
    exit 0
    ;;
  logs)
    tail -f "$BE_LOG" "$FE_LOG" 2>/dev/null
    exit 0
    ;;
  both|backend|frontend) ;;
  *) echo "Usage: $0 [both|backend|frontend|stop [backend|frontend]|logs]"; exit 1 ;;
esac

start_backend() {
  if [ ! -d "$REPO_DIR/backend/.venv" ]; then
    echo "ERROR: backend/.venv missing — run ./vast_setup.sh (VM) or create it first."; exit 1
  fi
  stop_one "$BE_PID" backend "$PORT" "uvicorn app.main"
  # --reload only when RELOAD=1 (dev). It spawns a child worker that survives a
  # plain kill and holds the port; a deploy box wants a single clean process.
  local reload=""; [ "${RELOAD:-0}" = "1" ] && reload="--reload"
  echo ">> Starting backend on http://$HOST:$PORT $reload…"
  (
    cd "$REPO_DIR/backend"
    source .venv/bin/activate
    exec uvicorn app.main:app --host "$HOST" --port "$PORT" $reload
  ) > "$BE_LOG" 2>&1 &
  echo $! > "$BE_PID"
}

start_frontend() {
  stop_one "$FE_PID" frontend 5173 "vite"
  echo ">> Starting frontend on http://localhost:5173  (API: ${VITE_API_URL:-http://localhost:8000}) …"
  (
    cd "$REPO_DIR/frontend"
    exec npm run dev
  ) > "$FE_LOG" 2>&1 &
  echo $! > "$FE_PID"
}

if [ "$MODE" = "both" ] || [ "$MODE" = "backend" ]; then start_backend; fi
if [ "$MODE" = "both" ] || [ "$MODE" = "frontend" ]; then start_frontend; fi

sleep 4
echo ""
echo "=== Running ($MODE) ==="
if [ "$MODE" != "frontend" ]; then echo "  Backend  : http://$HOST:$PORT   (health: /health)"; fi
if [ "$MODE" != "backend" ];  then echo "  Frontend : http://localhost:5173"; fi
echo "  Logs: ./run.sh logs      Stop: ./run.sh stop"
