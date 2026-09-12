from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from app.config import get_settings
from app.research.forward_oos import ForwardOOSAccumulator, ForwardOOSConfig
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import HistoricalReplayConfig
from app.research.historical_store import HistoricalResearchStore


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Accumulate fresh Phase 5.6 OOS trades and rerun frozen validation"
    )
    parser.add_argument("--discovery-store", required=True)
    parser.add_argument("--oos-store", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--until", required=True, help="UTC exclusive end date/time")
    parser.add_argument("--boundary", default="2026-09-01T00:00:00+00:00")
    parser.add_argument("--warmup-hours", type=int, default=300)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--quantity", type=float, default=0.001)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    discovery = HistoricalResearchStore(args.discovery_store).load()
    oos_store = HistoricalResearchStore(args.oos_store)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))

    symbol = args.symbol or settings.symbol
    timeframe = args.timeframe or settings.timeframe
    accumulator = ForwardOOSAccumulator(
        config=ForwardOOSConfig(
            boundary_iso=args.boundary,
            warmup_hours=args.warmup_hours,
        )
    )
    replay_config = HistoricalReplayConfig(
        symbol=symbol,
        timeframe=timeframe,
        quantity=args.quantity,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
    )
    dataset_run_id = (
        f"phase561-{symbol.replace('/', '')}-{timeframe}-{args.boundary}-{args.until}"
        f"-fee{args.fee_rate}-slip{args.slippage_bps}"
    )
    report = accumulator.accumulate(
        discovery_trades=discovery,
        manifest=manifest,
        oos_store=oos_store,
        market_data=HistoricalMarketDataService(settings.exchange_id),
        until_iso=args.until,
        replay_config=replay_config,
        dataset_run_id=dataset_run_id,
        git_commit=_git_commit(),
    )

    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(payload)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(f"Phase 5.6.1 report: {output}")


if __name__ == "__main__":
    main()
