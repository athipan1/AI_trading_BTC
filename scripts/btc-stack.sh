#!/usr/bin/env bash
set -euo pipefail

resolve_self() {
  local src="${BASH_SOURCE[0]}"
  if command -v readlink >/dev/null 2>&1; then
    src="$(readlink -f "$src" 2>/dev/null || printf '%s' "$src")"
  fi
  printf '%s' "$src"
}

SCRIPT_PATH="$(resolve_self)"
REPO_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
RUNTIME_DIR="$REPO_ROOT/runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"
HERMES3D_RUNTIME_DIR="${HERMES3D_RUNTIME_DIR:-/root/Hermes3D-runtime}"

COMPOSE_FILES=(
  -f "$REPO_ROOT/docker-compose.yml"
  -f "$REPO_ROOT/docker-compose.runtime.yml"
  -f "$REPO_ROOT/docker-compose.hermes3d.yml"
)

usage() {
  cat <<'EOF'
Usage: btc-stack <start|stop|restart|status|logs|doctor>

The installed aliases btc-start, btc-stop, and btc-status select the matching
command automatically. Docker Compose is preferred on Linux/VPS. Existing
Termux installations fall back to the native/proot runtime.
EOF
}

is_termux() {
  [[ "${PREFIX:-}" == *"com.termux"* ]] || [[ "${HOME:-}" == "/data/data/com.termux/"* ]]
}

has_docker_compose() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

backend() {
  case "${BTC_STACK_BACKEND:-auto}" in
    docker) printf 'docker\n' ;;
    termux) printf 'termux\n' ;;
    auto)
      if has_docker_compose; then
        printf 'docker\n'
      elif is_termux; then
        printf 'termux\n'
      else
        echo "No supported runtime found. Install Docker Compose or set BTC_STACK_BACKEND." >&2
        exit 2
      fi
      ;;
    *) echo "Unsupported BTC_STACK_BACKEND=${BTC_STACK_BACKEND}" >&2; exit 2 ;;
  esac
}

load_env() {
  if [[ ! -f "$REPO_ROOT/.env" ]]; then
    echo "Missing $REPO_ROOT/.env. Copy .env.example to .env and add testnet credentials." >&2
    exit 2
  fi
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
}

require_env() {
  local missing=0 name
  for name in \
    BINANCE_TESTNET_API_KEY \
    BINANCE_TESTNET_API_SECRET \
    BINANCE_FUTURES_TESTNET_API_KEY \
    BINANCE_FUTURES_TESTNET_API_SECRET; do
    if [[ -z "${!name:-}" ]]; then
      echo "MISSING: $name" >&2
      missing=1
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    echo "Refusing to start automatic testnet trading with incomplete credentials." >&2
    exit 2
  fi
}

docker_compose() {
  docker compose "${COMPOSE_FILES[@]}" "$@"
}

docker_start() {
  load_env
  require_env
  mkdir -p "$REPO_ROOT/state"
  docker_compose up -d --build
  docker_compose ps
  echo "Office: http://127.0.0.1:3000/office"
  echo "Runtime: http://127.0.0.1:8000/health"
}

docker_stop() {
  docker_compose down
}

docker_status() {
  docker_compose ps
}

docker_logs() {
  docker_compose logs -f --tail=100
}

docker_doctor() {
  echo "backend=docker"
  docker --version
  docker compose version
  [[ -f "$REPO_ROOT/.env" ]] && echo ".env=OK" || echo ".env=MISSING"
  docker_compose config --quiet && echo "compose=OK"
}

pid_alive() {
  local name="$1" pid_file="$PID_DIR/$1.pid" pid
  [[ -f "$pid_file" ]] || return 1
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

start_native() {
  local name="$1" command="$2"
  if pid_alive "$name"; then
    echo "$name: already running PID=$(cat "$PID_DIR/$name.pid")"
    return
  fi
  nohup bash -lc "cd '$REPO_ROOT'; export PYTHONPATH='$REPO_ROOT'; set -a; source '$REPO_ROOT/.env'; set +a; exec $command" \
    > "$LOG_DIR/$name.log" 2>&1 &
  echo $! > "$PID_DIR/$name.pid"
  echo "$name: started PID=$!"
}

termux_start_hermes() {
  if pid_alive hermes3d-office; then
    echo "hermes3d-office: already running PID=$(cat "$PID_DIR/hermes3d-office.pid")"
    return
  fi
  command -v proot-distro >/dev/null 2>&1 || {
    echo "proot-distro is required for Hermes3D on Termux." >&2
    exit 2
  }
  nohup proot-distro login ubuntu -- bash -lc "
    cd '$HERMES3D_RUNTIME_DIR'
    export HERMES3D_GATEWAY_URL=http://127.0.0.1:8000
    export HERMES3D_GATEWAY_ADAPTER_TYPE=custom
    export AI_TRADING_RUNTIME_URL=http://127.0.0.1:8000
    export CUSTOM_RUNTIME_ALLOWLIST=127.0.0.1,localhost
    exec npm start
  " > "$LOG_DIR/hermes3d-office.log" 2>&1 &
  echo $! > "$PID_DIR/hermes3d-office.pid"
  echo "hermes3d-office: started PID=$!"
}

termux_start() {
  load_env
  require_env
  export PYTHONPATH="$REPO_ROOT"
  mkdir -p "$LOG_DIR" "$PID_DIR" "$REPO_ROOT/state"

  start_native spot-auto "python scripts/run_binance_testnet_auto.py --watch --confirm BINANCE_TESTNET_AUTO"
  start_native futures-short "python scripts/run_binance_futures_testnet_short.py --watch --confirm BINANCE_FUTURES_TESTNET_SHORT"
  start_native spot-monitor "python scripts/monitor_binance_testnet_positions.py --watch --interval-seconds ${BTC_TESTNET_MONITOR_INTERVAL_SECONDS:-30}"
  start_native hermes3d-sidecar "python scripts/run_hermes3d_sidecar.py --spot-log runtime/logs/spot-auto.log --futures-log runtime/logs/futures-short.log --event-journal state/hermes3d-events.jsonl --cursor-store state/hermes3d-sidecar-cursor.json --interval-seconds 2"
  start_native trading-runtime "python -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000"
  termux_start_hermes

  sleep 3
  termux_status
}

termux_stop() {
  mkdir -p "$PID_DIR"
  local name pid_file pid
  for name in spot-auto futures-short spot-monitor hermes3d-sidecar trading-runtime; do
    pid_file="$PID_DIR/$name.pid"
    if [[ -f "$pid_file" ]]; then
      pid="$(cat "$pid_file" 2>/dev/null || true)"
      [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
      rm -f "$pid_file"
    fi
  done
  if command -v proot-distro >/dev/null 2>&1; then
    proot-distro login ubuntu -- bash -lc "pkill -f 'node server/index.js' 2>/dev/null || true" || true
  fi
  if [[ -f "$PID_DIR/hermes3d-office.pid" ]]; then
    pid="$(cat "$PID_DIR/hermes3d-office.pid" 2>/dev/null || true)"
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
    rm -f "$PID_DIR/hermes3d-office.pid"
  fi
  echo "BTC stack stopped"
}

termux_status() {
  local name
  echo "backend=termux"
  for name in spot-auto futures-short spot-monitor hermes3d-sidecar trading-runtime hermes3d-office; do
    if pid_alive "$name"; then
      echo "$name: RUNNING PID=$(cat "$PID_DIR/$name.pid")"
    else
      echo "$name: STOPPED"
    fi
  done
  printf 'runtime: '
  curl -fsS --max-time 3 http://127.0.0.1:8000/health 2>/dev/null || echo "DOWN"
  printf '\noffice: '
  curl -fsS -o /dev/null --max-time 3 -w 'HTTP=%{http_code}\n' http://127.0.0.1:3000/office 2>/dev/null || echo "DOWN"
}

termux_logs() {
  tail -n 100 -f \
    "$LOG_DIR/spot-auto.log" \
    "$LOG_DIR/futures-short.log" \
    "$LOG_DIR/spot-monitor.log" \
    "$LOG_DIR/hermes3d-sidecar.log" \
    "$LOG_DIR/trading-runtime.log" \
    "$LOG_DIR/hermes3d-office.log"
}

termux_doctor() {
  echo "backend=termux"
  command -v python >/dev/null && python --version || echo "python=MISSING"
  command -v proot-distro >/dev/null && echo "proot-distro=OK" || echo "proot-distro=MISSING"
  [[ -d "$HERMES3D_RUNTIME_DIR" ]] && echo "hermes-runtime=OK" || echo "hermes-runtime=CHECK_INSIDE_UBUNTU"
  [[ -f "$REPO_ROOT/.env" ]] && echo ".env=OK" || echo ".env=MISSING"
}

COMMAND="${1:-}"
case "$(basename "$0")" in
  btc-start) COMMAND=start ;;
  btc-stop) COMMAND=stop ;;
  btc-status) COMMAND=status ;;
  btc-logs) COMMAND=logs ;;
esac

[[ -n "$COMMAND" ]] || { usage; exit 2; }
BACKEND="$(backend)"

case "$BACKEND:$COMMAND" in
  docker:start) docker_start ;;
  docker:stop) docker_stop ;;
  docker:restart) docker_stop; docker_start ;;
  docker:status) docker_status ;;
  docker:logs) docker_logs ;;
  docker:doctor) docker_doctor ;;
  termux:start) termux_start ;;
  termux:stop) termux_stop ;;
  termux:restart) termux_stop; termux_start ;;
  termux:status) termux_status ;;
  termux:logs) termux_logs ;;
  termux:doctor) termux_doctor ;;
  *) usage; exit 2 ;;
esac
