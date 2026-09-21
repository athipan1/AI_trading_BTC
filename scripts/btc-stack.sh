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
HERMES3D_REF="${HERMES3D_REF:-beb76292747b816ef317aa6f9a3992e0014f81d9}"
HERMES3D_REPO_URL="${HERMES3D_REPO_URL:-https://github.com/iamlukethedev/Hermes3D.git}"
PHASE562_CONFIG="${PHASE562_CONFIG:-$HOME/.config/ai_trading_btc/phase562_daily.env}"

COMPOSE_FILES=(
  -f "$REPO_ROOT/docker-compose.yml"
  -f "$REPO_ROOT/docker-compose.runtime.yml"
  -f "$REPO_ROOT/docker-compose.hermes3d.yml"
)

usage() {
  cat <<'EOF'
Usage: btc-stack <start|stop|restart|status|logs|doctor|office-start|office-stop|office-restart|office-status|office-rebuild>

The installed aliases btc-start, btc-stop, btc-status, btc-logs and
btc-office-* select the matching command automatically. Docker Compose is
preferred on Linux/VPS. Existing Termux installations fall back to the
native/proot runtime.
EOF
}

is_termux() {
  [[ "${PREFIX:-}" == *"com.termux"* ]] || [[ "${HOME:-}" == "/data/data/com.termux/"* ]]
}

is_termux_proot_guest() {
  [[ -x /usr/bin/bash ]] || return 1
  [[ -f /etc/os-release ]] || return 1
  grep -Eq '^ID=(ubuntu|debian)$' /etc/os-release || return 1
  [[ -d /data/data/com.termux/files/usr ]] || return 1
}

require_proot_distro() {
  command -v proot-distro >/dev/null 2>&1 || {
    echo "proot-distro is required for Hermes3D on Termux host." >&2
    return 2
  }
}

hermes_guest_exec() {
  local guest_command="$1"
  if is_termux_proot_guest; then
    bash -lc "$guest_command"
    return
  fi
  require_proot_distro
  proot-distro login ubuntu -- bash -lc "$guest_command"
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
      elif is_termux || is_termux_proot_guest; then
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

docker_office_start() {
  docker_compose up -d --no-deps hermes3d
}

docker_office_stop() {
  docker_compose stop hermes3d
}

docker_office_status() {
  docker_compose ps hermes3d
}

docker_office_rebuild() {
  docker_compose build hermes3d
  docker_compose up -d --no-deps hermes3d
  docker_office_status
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
  nohup bash -lc "cd '$REPO_ROOT'; export PYTHONPATH='$REPO_ROOT'; export PYTHONUNBUFFERED=1; set -a; source '$REPO_ROOT/.env'; set +a; exec $command" \
    > "$LOG_DIR/$name.log" 2>&1 &
  echo $! > "$PID_DIR/$name.pid"
  echo "$name: started PID=$!"
}

termux_start_research_scheduler() {
  if [[ ! -f "$PHASE562_CONFIG" ]]; then
    echo "phase562-scheduler: config missing at $PHASE562_CONFIG" >&2
    echo "Run scripts/install_phase562_daily_cron.sh once to create the Phase 5.6.2 runtime config." >&2
    return 1
  fi
  start_native phase562-scheduler \
    "python scripts/run_phase562_termux_scheduler.py --runner scripts/run_phase562_daily.sh --state runtime/phase562_daily_scheduler_state.json --timezone Asia/Bangkok --hour 7 --minute 10 --poll-seconds 60"
}

hermes3d_node_pid() {
  hermes_guest_exec "pgrep -f '^node server/index.js$' | head -n 1" 2>/dev/null
}

refresh_hermes3d_pid() {
  local pid
  mkdir -p "$PID_DIR"
  pid="$(hermes3d_node_pid || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    printf '%s\n' "$pid" > "$PID_DIR/hermes3d-office.pid"
    return 0
  fi
  rm -f "$PID_DIR/hermes3d-office.pid"
  return 1
}

termux_start_hermes() {
  local launcher_pid attempt
  local start_command
  mkdir -p "$LOG_DIR" "$PID_DIR"
  if refresh_hermes3d_pid; then
    echo "hermes3d-office: already running PID=$(cat "$PID_DIR/hermes3d-office.pid")"
    return
  fi

  start_command="
    cd '$HERMES3D_RUNTIME_DIR'
    export HERMES3D_GATEWAY_URL=http://127.0.0.1:8000
    export HERMES3D_GATEWAY_ADAPTER_TYPE=custom
    export AI_TRADING_RUNTIME_URL=http://127.0.0.1:8000
    export CUSTOM_RUNTIME_ALLOWLIST=127.0.0.1,localhost
    exec npm start
  "

  if is_termux_proot_guest; then
    nohup bash -lc "$start_command" > "$LOG_DIR/hermes3d-office.log" 2>&1 &
  else
    require_proot_distro
    nohup proot-distro login ubuntu -- bash -lc "$start_command" \
      > "$LOG_DIR/hermes3d-office.log" 2>&1 &
  fi
  launcher_pid=$!

  for attempt in $(seq 1 20); do
    if refresh_hermes3d_pid; then
      echo "hermes3d-office: started PID=$(cat "$PID_DIR/hermes3d-office.pid") launcher=$launcher_pid"
      return
    fi
    sleep 1
  done

  echo "hermes3d-office: failed to discover node server PID after launch PID=$launcher_pid" >&2
  return 1
}

termux_stop_hermes() {
  local pid
  if refresh_hermes3d_pid; then
    pid="$(cat "$PID_DIR/hermes3d-office.pid")"
    kill "$pid" 2>/dev/null || true
  fi
  hermes_guest_exec "pkill -f '^node server/index.js$' 2>/dev/null || true" || true
  rm -f "$PID_DIR/hermes3d-office.pid"
}

termux_office_status() {
  if refresh_hermes3d_pid; then
    echo "hermes3d-office: RUNNING PID=$(cat "$PID_DIR/hermes3d-office.pid")"
  else
    echo "hermes3d-office: STOPPED"
  fi
  printf 'office: '
  curl -fsS -o /dev/null --max-time 3 -w 'HTTP=%{http_code}\n' http://127.0.0.1:3000/office 2>/dev/null || echo "DOWN"
  echo "hermes3d-ref: $HERMES3D_REF"
}

termux_prepare_hermes_staging() {
  local staging_dir="${HERMES3D_RUNTIME_DIR}.next"
  hermes_guest_exec "
    set -euo pipefail
    command -v git >/dev/null
    command -v node >/dev/null
    command -v npm >/dev/null
    rm -rf '$staging_dir'
    git clone '$HERMES3D_REPO_URL' '$staging_dir'
    cd '$staging_dir'
    git checkout '$HERMES3D_REF'
    cp -a '$REPO_ROOT/deploy/hermes3d/overlay/.' '$staging_dir/'
    node scripts/apply-trading-speech-ux.mjs
    npm ci
    npm run build
    test -f package.json
    test -f server/index.js
  "
}

termux_swap_hermes_runtime() {
  local staging_dir="${HERMES3D_RUNTIME_DIR}.next"
  local backup_dir="${HERMES3D_RUNTIME_DIR}.previous"
  hermes_guest_exec "
    set -euo pipefail
    rm -rf '$backup_dir'
    if [[ -d '$HERMES3D_RUNTIME_DIR' ]]; then
      mv '$HERMES3D_RUNTIME_DIR' '$backup_dir'
    fi
    mv '$staging_dir' '$HERMES3D_RUNTIME_DIR'
  "
}

termux_restore_hermes_runtime() {
  local backup_dir="${HERMES3D_RUNTIME_DIR}.previous"
  hermes_guest_exec "
    set -euo pipefail
    rm -rf '$HERMES3D_RUNTIME_DIR'
    if [[ -d '$backup_dir' ]]; then
      mv '$backup_dir' '$HERMES3D_RUNTIME_DIR'
    fi
  "
}

termux_cleanup_hermes_backup() {
  local backup_dir="${HERMES3D_RUNTIME_DIR}.previous"
  hermes_guest_exec "rm -rf '$backup_dir'" || true
}

termux_office_rebuild() {
  local was_running=0 attempt
  if refresh_hermes3d_pid; then
    was_running=1
  fi

  echo "Building Hermes3D staging runtime at ref $HERMES3D_REF"
  termux_prepare_hermes_staging

  if [[ "$was_running" -eq 1 ]]; then
    termux_stop_hermes
  fi

  termux_swap_hermes_runtime

  if ! termux_start_hermes; then
    echo "Hermes3D start failed; restoring previous runtime." >&2
    termux_stop_hermes || true
    termux_restore_hermes_runtime
    if [[ "$was_running" -eq 1 ]]; then
      termux_start_hermes || true
    fi
    return 1
  fi

  for attempt in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 3 http://127.0.0.1:3000/office; then
      termux_cleanup_hermes_backup
      echo "hermes3d-office: rebuild complete"
      termux_office_status
      return 0
    fi
    sleep 1
  done

  echo "Hermes3D health check failed; restoring previous runtime." >&2
  termux_stop_hermes || true
  termux_restore_hermes_runtime
  if [[ "$was_running" -eq 1 ]]; then
    termux_start_hermes || true
  fi
  return 1
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
  termux_start_research_scheduler
  termux_start_hermes

  sleep 3
  termux_status
}

termux_stop() {
  mkdir -p "$PID_DIR"
  local name pid_file pid
  for name in spot-auto futures-short spot-monitor hermes3d-sidecar trading-runtime phase562-scheduler; do
    pid_file="$PID_DIR/$name.pid"
    if [[ -f "$pid_file" ]]; then
      pid="$(cat "$pid_file" 2>/dev/null || true)"
      [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
      rm -f "$pid_file"
    fi
  done
  termux_stop_hermes
  echo "BTC stack stopped"
}

termux_status() {
  local name
  echo "backend=termux"
  for name in spot-auto futures-short spot-monitor hermes3d-sidecar trading-runtime phase562-scheduler; do
    if pid_alive "$name"; then
      echo "$name: RUNNING PID=$(cat "$PID_DIR/$name.pid")"
    else
      echo "$name: STOPPED"
    fi
  done
  if refresh_hermes3d_pid; then
    echo "hermes3d-office: RUNNING PID=$(cat "$PID_DIR/hermes3d-office.pid")"
  else
    echo "hermes3d-office: STOPPED"
  fi
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
    "$LOG_DIR/phase562-scheduler.log" \
    "$LOG_DIR/hermes3d-office.log"
}

termux_doctor() {
  echo "backend=termux"
  command -v python >/dev/null && python --version || echo "python=MISSING"
  if is_termux_proot_guest; then
    echo "termux-context=proot-guest"
    echo "proot-distro=HOST_ONLY"
  else
    command -v proot-distro >/dev/null && echo "termux-context=host" || echo "termux-context=unknown"
    command -v proot-distro >/dev/null && echo "proot-distro=OK" || echo "proot-distro=MISSING"
  fi
  [[ -d "$HERMES3D_RUNTIME_DIR" ]] && echo "hermes-runtime=OK" || echo "hermes-runtime=CHECK_INSIDE_UBUNTU"
  [[ -f "$REPO_ROOT/.env" ]] && echo ".env=OK" || echo ".env=MISSING"
  [[ -f "$PHASE562_CONFIG" ]] && echo "phase562-config=OK" || echo "phase562-config=MISSING"
  [[ -f "$REPO_ROOT/scripts/run_phase562_termux_scheduler.py" ]] && echo "phase562-scheduler=OK" || echo "phase562-scheduler=MISSING"
}

COMMAND="${1:-}"
case "$(basename "$0")" in
  btc-start) COMMAND=start ;;
  btc-stop) COMMAND=stop ;;
  btc-status) COMMAND=status ;;
  btc-logs) COMMAND=logs ;;
  btc-office-start) COMMAND=office-start ;;
  btc-office-stop) COMMAND=office-stop ;;
  btc-office-restart) COMMAND=office-restart ;;
  btc-office-status) COMMAND=office-status ;;
  btc-office-rebuild) COMMAND=office-rebuild ;;
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
  docker:office-start) docker_office_start ;;
  docker:office-stop) docker_office_stop ;;
  docker:office-restart) docker_office_stop; docker_office_start ;;
  docker:office-status) docker_office_status ;;
  docker:office-rebuild) docker_office_rebuild ;;
  termux:start) termux_start ;;
  termux:stop) termux_stop ;;
  termux:restart) termux_stop; termux_start ;;
  termux:status) termux_status ;;
  termux:logs) termux_logs ;;
  termux:doctor) termux_doctor ;;
  termux:office-start) termux_start_hermes ;;
  termux:office-stop) termux_stop_hermes ;;
  termux:office-restart) termux_stop_hermes; termux_start_hermes ;;
  termux:office-status) termux_office_status ;;
  termux:office-rebuild) termux_office_rebuild ;;
  *) usage; exit 2 ;;
esac
