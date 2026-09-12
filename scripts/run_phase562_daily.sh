#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG_FILE="${PHASE562_CONFIG:-$HOME/.config/ai_trading_btc/phase562_daily.env}"
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Phase 5.6.2 config not found: $CONFIG_FILE" >&2
  exit 2
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

: "${REPO_DIR:?REPO_DIR is required}"
: "${RESEARCH_DIR:?RESEARCH_DIR is required}"
: "${PYTHON_BIN:?PYTHON_BIN is required}"

LOCK_DIR="${LOCK_DIR:-$RESEARCH_DIR/.phase562_daily.lock}"
LOG_DIR="${LOG_DIR:-$RESEARCH_DIR/logs}"
mkdir -p "$LOG_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Phase 5.6.2 daily run skipped: lock already exists at $LOCK_DIR"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

cd "$REPO_DIR"
export PYTHONPATH="${PYTHONPATH:-.}"

"$PYTHON_BIN" scripts/run_phase562_forward_oos_automation.py \
  --discovery-store "$RESEARCH_DIR/btc_h1_2021_2026_gap_aware.json" \
  --oos-store "$RESEARCH_DIR/phase56_fresh_oos.json" \
  --manifest "$RESEARCH_DIR/phase56_frozen_manifest.json" \
  --checkpoint "$RESEARCH_DIR/phase562_forward_oos_checkpoint.json" \
  --boundary 2026-09-01T00:00:00+00:00 \
  --warmup-hours 288 \
  --symbol BTC/USDT \
  --timeframe 1h \
  --quantity 0.001 \
  --fee-rate 0.001 \
  --slippage-bps 2 \
  --output "$RESEARCH_DIR/phase562_forward_oos.json"

"$PYTHON_BIN" scripts/run_phase563_oos_promotion_gate.py \
  --discovery-store "$RESEARCH_DIR/btc_h1_2021_2026_gap_aware.json" \
  --oos-store "$RESEARCH_DIR/phase56_fresh_oos.json" \
  --manifest "$RESEARCH_DIR/phase56_frozen_manifest.json" \
  --gate-manifest "$RESEARCH_DIR/phase563_promotion_gate_manifest.json" \
  --output "$RESEARCH_DIR/phase563_promotion_gate.json"
