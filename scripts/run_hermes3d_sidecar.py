from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.sidecar import (
    Hermes3DLegacyLogSidecar,
    Hermes3DSidecarCursorStore,
    LogSource,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Hermes3D sidecar for already-running Termux traders"
    )
    parser.add_argument("--spot-log", default="spot-long.log")
    parser.add_argument("--futures-log", default="futures-short.log")
    parser.add_argument(
        "--event-journal",
        default=os.environ.get("HERMES3D_EVENT_JOURNAL", "state/hermes3d-events.jsonl"),
    )
    parser.add_argument(
        "--cursor-store",
        default="state/hermes3d-sidecar-cursors.json",
    )
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="Replay existing log content. Default starts at EOF for zero-downtime attach.",
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")

    sidecar = Hermes3DLegacyLogSidecar(
        sources=[
            LogSource("spot", Path(args.spot_log)),
            LogSource("futures-short", Path(args.futures_log)),
        ],
        journal=Hermes3DEventJournal(args.event_journal),
        cursor_store=Hermes3DSidecarCursorStore(args.cursor_store),
        start_at_end=not args.from_start,
    )

    print(
        json.dumps(
            {
                "event": "HERMES3D_SIDECAR_READY",
                "mode": "read_only",
                "spot_log": args.spot_log,
                "futures_log": args.futures_log,
                "event_journal": args.event_journal,
                "cursor_store": args.cursor_store,
                "start_at_end": not args.from_start,
                "exchange_access": False,
                "execution_access": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    if args.once:
        print(json.dumps(sidecar.poll_once(), sort_keys=True), flush=True)
        return
    sidecar.run_forever(args.interval_seconds)


if __name__ == "__main__":
    main()
