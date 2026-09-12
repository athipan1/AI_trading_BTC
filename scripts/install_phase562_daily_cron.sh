#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RESEARCH_DIR="${RESEARCH_DIR:-/workspace/research}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python || true)}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/ai_trading_btc}"
CONFIG_FILE="$CONFIG_DIR/phase562_daily.env"
RUNNER="$REPO_DIR/scripts/run_phase562_daily.sh"
LOG_DIR="$RESEARCH_DIR/logs"
CRON_MARKER="# AI_TRADING_BTC_PHASE562_DAILY"
CRON_LINE="10 7 * * * $RUNNER >> $LOG_DIR/phase562_daily.log 2>&1 $CRON_MARKER"

if [[ -z "$PYTHON_BIN" ]]; then
  echo "python executable not found in current environment" >&2
  exit 2
fi
if ! command -v crontab >/dev/null 2>&1; then
  echo "crontab not found. Install cron/cronie in the environment that will stay running, then rerun this installer." >&2
  exit 3
fi

mkdir -p "$CONFIG_DIR" "$LOG_DIR"
cat > "$CONFIG_FILE" <<EOF
REPO_DIR='$REPO_DIR'
RESEARCH_DIR='$RESEARCH_DIR'
PYTHON_BIN='$PYTHON_BIN'
LOG_DIR='$LOG_DIR'
EOF
chmod 600 "$CONFIG_FILE"
chmod +x "$RUNNER"

CURRENT="$(crontab -l 2>/dev/null || true)"
FILTERED="$(printf '%s\n' "$CURRENT" | grep -v 'AI_TRADING_BTC_PHASE562_DAILY' || true)"
{
  printf '%s\n' "$FILTERED"
  printf '%s\n' 'CRON_TZ=Asia/Bangkok'
  printf '%s\n' "$CRON_LINE"
} | sed '/^[[:space:]]*$/N;/^\n$/D' | crontab -

printf 'Installed Phase 5.6.2 daily schedule at 07:10 Asia/Bangkok.\n'
printf 'Python: %s\n' "$PYTHON_BIN"
printf 'Runner: %s\n' "$RUNNER"
printf 'Log: %s\n' "$LOG_DIR/phase562_daily.log"
printf '\nCurrent cron entries:\n'
crontab -l
