from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.research.historical_diagnostics import HistoricalDatasetDiagnostics
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import (
    HistoricalReplayConfig,
    HistoricalStrategyReplay,
    canonical_replay_strategies,
)
from app.research.historical_store import HistoricalResearchStore


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


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
    parser = argparse.ArgumentParser(description="Build persistent historical BTC research trades")
    parser.add_argument("--since", required=True, help="UTC date, for example 2021-01-01")
    parser.add_argument("--until", required=True, help="UTC exclusive end date")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--quantity", type=float, default=0.001)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--store", default=None)
    parser.add_argument(
        "--report",
        default="state/research/historical-diagnostics.json",
        help="JSON diagnostics report path",
    )
    parser.add_argument(
        "--fail-on-gaps",
        action="store_true",
        help="fail after diagnostics when candle gaps or timestamp anomalies are detected",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    symbol = args.symbol or settings.symbol
    timeframe = args.timeframe or settings.timeframe
    store_path = args.store or settings.research_historical_trade_store
    since_ms = _ms(args.since)
    until_ms = _ms(args.until)
    if until_ms <= since_ms:
        raise ValueError("--until must be after --since")

    service = HistoricalMarketDataService(settings.exchange_id)
    candles = service.fetch_range(
        symbol,
        timeframe,
        since_ms=since_ms,
        until_ms=until_ms,
    )
    config = HistoricalReplayConfig(
        symbol=symbol,
        timeframe=timeframe,
        quantity=args.quantity,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
    )
    engine = HistoricalStrategyReplay(config)
    store = HistoricalResearchStore(store_path)
    commit = _git_commit()
    dataset_run_id = (
        f"{symbol.replace('/', '')}-{timeframe}-{args.since}-{args.until}"
        f"-fee{args.fee_rate}-slip{args.slippage_bps}"
    )

    print(f"Historical candles: {len(candles)}")
    total_closed = 0
    for strategy in canonical_replay_strategies():
        replay = engine.replay(candles, strategy)
        result = store.upsert_replay(
            replay,
            dataset_run_id=dataset_run_id,
            git_commit=commit,
        )
        closed = int(replay["closed_trades"])
        total_closed += closed
        print(
            f"{strategy.strategy_id}: closed={closed} inserted={result['inserted']} "
            f"updated={result['updated']} store_total={result['total']}"
        )

    stored_trades = store.load()
    diagnostics = HistoricalDatasetDiagnostics.build(
        candles=candles,
        trades=stored_trades,
        timeframe=timeframe,
    )
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    continuity = diagnostics["candle_continuity"]
    coverage = diagnostics["trade_coverage"]
    quality = diagnostics["feature_quality"]
    split = diagnostics["temporal_split"]

    print(f"Total closed replay trades: {total_closed}")
    print(f"Historical research store: {store_path}")
    print(f"Diagnostics report: {report_path}")
    print(
        "Candle continuity: "
        f"{continuity['status']} gaps={continuity['gap_count']} "
        f"missing_intervals={continuity['missing_intervals']} "
        f"duplicates={continuity['duplicate_timestamps']} "
        f"out_of_order={continuity['out_of_order_timestamps']}"
    )
    print(f"Trade sample size: {coverage['sample_size']}")
    print(f"Trades by strategy: {coverage['strategies']}")
    print(f"Trades by regime: {coverage['market_regimes']}")
    print(f"Trades by year: {coverage['years']}")
    print(
        "Dataset readiness: "
        f"{quality['readiness']['dataset']} training={quality['readiness']['training']} "
        f"coverage={quality['quality']['feature_coverage_pct']}%"
    )
    print(
        "Chronological split: "
        f"{split['counts']} readiness={split['readiness']} random_shuffle={split['random_shuffle']}"
    )
    print("Production PositionStore mutated: False")

    if args.fail_on_gaps and continuity["status"] != "PASS":
        raise RuntimeError("historical candle continuity check failed")


if __name__ == "__main__":
    main()
