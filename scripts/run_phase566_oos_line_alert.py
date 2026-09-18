from __future__ import annotations

import argparse
import os

from app.notifications.line_messaging import LineMessagingNotifier
from app.research.oos_line_alerts import (
    build_snapshot,
    format_daily_heartbeat_message,
    format_oos_line_message,
    load_alert_state,
    should_notify,
    write_alert_state,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send Phase 5.6.6 OOS LINE alerts and heartbeats.")
    parser.add_argument("--promotion", required=True)
    parser.add_argument("--integrity", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument(
        "--daily-heartbeat",
        action="store_true",
        help="Send one heartbeat for this invocation even when OOS state is unchanged.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = build_snapshot(
        promotion_path=args.promotion,
        integrity_path=args.integrity,
        checkpoint_path=args.checkpoint,
    )
    previous = load_alert_state(args.state)
    changed = should_notify(snapshot, previous)

    if not changed and not args.daily_heartbeat:
        print("Phase 5.6.6: no OOS state change; LINE alert skipped.")
        return 0

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    target_id = os.environ.get("LINE_TARGET_ID", "").strip()
    if not token or not target_id:
        print("Phase 5.6.6: LINE credentials not configured; alert skipped.")
        return 0

    notifier = LineMessagingNotifier(token, target_id)
    if changed:
        notifier.send_text(format_oos_line_message(snapshot))
        write_alert_state(args.state, snapshot)
        print("Phase 5.6.6: OOS LINE alert sent and dedup state advanced.")
        return 0

    notifier.send_text(format_daily_heartbeat_message(snapshot, evidence_changed=False))
    print("Phase 5.6.6: daily OOS heartbeat sent; dedup state unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
