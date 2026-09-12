#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="$SCRIPT_DIR/btc-stack.sh"

if [[ ! -f "$LAUNCHER" ]]; then
  echo "Missing launcher: $LAUNCHER" >&2
  exit 2
fi

chmod +x "$LAUNCHER"

if [[ "${PREFIX:-}" == *"com.termux"* ]]; then
  INSTALL_DIR="$PREFIX/bin"
  RUN_AS=()
else
  INSTALL_DIR="${BTC_COMMAND_INSTALL_DIR:-/usr/local/bin}"
  if [[ -w "$INSTALL_DIR" ]] || { [[ ! -e "$INSTALL_DIR" ]] && [[ -w "$(dirname "$INSTALL_DIR")" ]]; }; then
    RUN_AS=()
  elif command -v sudo >/dev/null 2>&1; then
    RUN_AS=(sudo)
  else
    echo "Cannot write $INSTALL_DIR and sudo is unavailable." >&2
    exit 2
  fi
fi

"${RUN_AS[@]}" mkdir -p "$INSTALL_DIR"
for command in btc-start btc-stop btc-status btc-logs; do
  "${RUN_AS[@]}" ln -sfn "$LAUNCHER" "$INSTALL_DIR/$command"
done

echo "Installed commands in $INSTALL_DIR:"
echo "  btc-start"
echo "  btc-stop"
echo "  btc-status"
echo "  btc-logs"
