#!/usr/bin/env bash
# Start/stop/restart the backend (FastAPI/uvicorn) and frontend (Vite) dev servers
# together, for local non-Docker development - automates the two-terminal manual
# steps in README's "Quickstart: Web UI". Assumes `uvicorn`/`alembic` on PATH already
# resolve to the project's pyenv virtualenv (see .python-version) - if not, activate
# it first.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

RUN_DIR=".dev"
API_PID_FILE="$RUN_DIR/api.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"
API_LOG="$RUN_DIR/api.log"
WEB_LOG="$RUN_DIR/web.log"
API_PORT="${LEXIS_API_PORT:-8000}"
WEB_PORT="${LEXIS_WEB_PORT:-5173}"

# Each process is launched via `setsid` so it becomes its own process-group leader -
# that lets `stop` kill the whole group (npm's `run dev` and uvicorn's `--reload`
# both spawn a child process; killing just the parent PID would orphan it).
HAVE_SETSID=1
command -v setsid >/dev/null 2>&1 || HAVE_SETSID=0

mkdir -p "$RUN_DIR"

is_running() {
  [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null
}

start_one() {
  local name="$1" pid_file="$2" log_file="$3"
  shift 3
  if is_running "$pid_file"; then
    echo "$name already running (pid $(cat "$pid_file"))"
    return
  fi
  if [[ "$HAVE_SETSID" == 1 ]]; then
    setsid "$@" > "$log_file" 2>&1 < /dev/null &
  else
    "$@" > "$log_file" 2>&1 < /dev/null &
  fi
  echo $! > "$pid_file"
  echo "$name started (pid $(cat "$pid_file"), log: $log_file)"
}

stop_one() {
  local name="$1" pid_file="$2"
  if ! is_running "$pid_file"; then
    echo "$name not running"
    rm -f "$pid_file"
    return
  fi
  local pid; pid="$(cat "$pid_file")"
  echo "Stopping $name (pid $pid)..."
  kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 25); do
    is_running "$pid_file" || break
    sleep 0.2
  done
  if is_running "$pid_file"; then
    echo "  still running, sending SIGKILL"
    kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

start() {
  if ! command -v uvicorn >/dev/null 2>&1 || ! command -v alembic >/dev/null 2>&1; then
    echo "error: uvicorn/alembic not found on PATH - activate the project's pyenv" >&2
    echo "       virtualenv first (see .python-version), e.g. 'pyenv activate lexis'" >&2
    echo "       or 'pip install -e \".[dev,api]\"' if it's not installed there yet." >&2
    exit 1
  fi
  if [[ ! -d frontend/node_modules ]]; then
    echo "Installing frontend dependencies (first run)..."
    (cd frontend && npm install)
  fi

  echo "Running migrations..."
  alembic upgrade head

  start_one "Backend" "$API_PID_FILE" "$API_LOG" \
    uvicorn lexis_api.main:app --reload --port "$API_PORT"
  start_one "Frontend" "$WEB_PID_FILE" "$WEB_LOG" \
    npm --prefix frontend run dev -- --port "$WEB_PORT"

  echo
  echo "Backend:  http://localhost:$API_PORT  (log: $API_LOG)"
  echo "Frontend: http://localhost:$WEB_PORT  (log: $WEB_LOG)"
  echo "Tail logs with: tail -f $API_LOG $WEB_LOG"
}

stop() {
  stop_one "Backend" "$API_PID_FILE"
  stop_one "Frontend" "$WEB_PID_FILE"
}

status() {
  is_running "$API_PID_FILE" \
    && echo "Backend:  running (pid $(cat "$API_PID_FILE"))" \
    || echo "Backend:  not running"
  is_running "$WEB_PID_FILE" \
    && echo "Frontend: running (pid $(cat "$WEB_PID_FILE"))" \
    || echo "Frontend: not running"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}" >&2
    echo "Env overrides: LEXIS_API_PORT (default 8000), LEXIS_WEB_PORT (default 5173)" >&2
    exit 1
    ;;
esac
