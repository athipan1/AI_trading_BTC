from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from app.integrations.hermes3d.journal import Hermes3DEventJournal

DEFAULT_JOURNAL = Path("state/hermes3d-events.jsonl")
DEFAULT_STRATEGY_ID = "triple_ema"


def build_validation_events(strategy_id: str) -> list[dict[str, Any]]:
    validation_order_id = f"phase17-validation-{int(time.time())}"
    common = {
        "strategy_id": strategy_id,
        "validation": True,
        "read_only": True,
        "source": "phase-1.7.2-live-office-validation",
    }
    return [
        {
            "event": "BUY_READY",
            "agent_id": strategy_id,
            "payload": {
                **common,
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "signal": {"action": "BUY", "validation": True},
            },
        },
        {
            "event": "RISK_PASS",
            "agent_id": "risk-manager",
            "payload": {
                **common,
                "signal_action": "BUY",
                "risk": {"approved": True, "validation": True},
            },
        },
        {
            "event": "ORDER_OPEN",
            "agent_id": "positions",
            "payload": {
                **common,
                "order_id": validation_order_id,
                "symbol": "BTC/USDT",
                "side": "BUY",
                "entry_price": 0,
                "quantity": 0,
                "take_profit": 0,
                "stop_loss": 0,
            },
        },
    ]


def emit_validation_sequence(
    *,
    journal_path: str | Path,
    strategy_id: str,
    interval_seconds: float,
) -> list[dict[str, Any]]:
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be non-negative")

    journal = Hermes3DEventJournal(journal_path)
    published: list[dict[str, Any]] = []
    events = build_validation_events(strategy_id)

    for index, item in enumerate(events):
        record = journal.publish(
            event=str(item["event"]),
            agent_id=str(item["agent_id"]),
            payload=dict(item["payload"]),
        )
        published.append(record)
        print(
            f"[phase-1.7.2] published {record['event']} -> {record['agent_id']} "
            f"read_only=true validation=true"
        )
        if interval_seconds and index < len(events) - 1:
            time.sleep(interval_seconds)

    return published


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Emit a synthetic read-only Hermes3D validation sequence into the local "
            "event journal. This script never imports or calls exchange execution code."
        )
    )
    parser.add_argument(
        "--event-journal",
        default=str(DEFAULT_JOURNAL),
        help="Hermes3D JSONL event journal path.",
    )
    parser.add_argument(
        "--strategy-id",
        default=DEFAULT_STRATEGY_ID,
        help="Existing Hermes3D strategy agent id to animate.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=2.0,
        help="Delay between BUY_READY, RISK_PASS, and ORDER_OPEN validation events.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    emit_validation_sequence(
        journal_path=args.event_journal,
        strategy_id=args.strategy_id,
        interval_seconds=args.interval_seconds,
    )


if __name__ == "__main__":
    main()
