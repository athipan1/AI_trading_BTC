from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.research.daily_scheduler import DailyResearchScheduler, DailySchedulerConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persistent Phase 5.6.2/5.6.3 daily scheduler for Termux/PRoot runtimes."
    )
    parser.add_argument(
        "--runner",
        default="scripts/run_phase562_daily.sh",
        help="Path to the existing Phase 5.6.2 daily runner.",
    )
    parser.add_argument(
        "--state",
        default="runtime/phase562_daily_scheduler_state.json",
        help="Scheduler state file used to guarantee at most one successful run per local day.",
    )
    parser.add_argument("--timezone", default="Asia/Bangkok")
    parser.add_argument("--hour", type=int, default=7)
    parser.add_argument("--minute", type=int, default=10)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Evaluate the schedule once and exit. Useful for smoke tests.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    scheduler = DailyResearchScheduler(
        DailySchedulerConfig(
            timezone=args.timezone,
            run_hour=args.hour,
            run_minute=args.minute,
            poll_seconds=args.poll_seconds,
        )
    )
    runner = Path(args.runner)
    state = Path(args.state)
    if args.once:
        result = scheduler.run_once(runner=runner, state_path=state)
        print(result)
        return 0 if result in {"SUCCESS", "NOT_DUE"} else 1
    scheduler.run_forever(runner=runner, state_path=state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
