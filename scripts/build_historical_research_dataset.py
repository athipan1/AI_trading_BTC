from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime

from app.config import get_settings
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.historical_diagnostics import HistoricalResearchDiagnostics
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import (
    HistoricalReplayConfig,
    HistoricalStrategyReplay,
    canonical_replay_strategies,
)
from app.research.historical_store import HistoricalResearchStore
from app.research.runtime_acceptance import evaluate_phase51_runtime_acceptance


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
        "--gap-policy",
        choices=("reject", "segment"),
        default="reject",
        help=(
            "reject source gaps, or segment replay so no strategy/indicator state crosses a gap"
        ),
    )
    parser.add_argument(
        "--require-complete-range",
        action="store_true",
        help="Fail when the requested OHLCV range contains gaps or partial coverage",
    )
    parser.add_argument(
        "--require-phase51-acceptance",
        action="store_true",
        help="Fail unless the persisted dataset passes the Phase 5.1 runtime acceptance gate",
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
    integrity = service.integrity_report(
        candles,
        timeframe=timeframe,
        since_ms=since_ms,
        until_ms=until_ms,
    )
    print(f"Historical candles: {len(candles)}")
    print(f"OHLCV integrity: {json.dumps(integrity, sort_keys=True)}")

    if args.require_complete_range and not integrity["complete_range"]:
        raise RuntimeError("historical OHLCV range failed completeness check")
    if not integrity["segment_replay_safe"]:
        raise RuntimeError("historical OHLCV range is unsafe for segmented replay")
    missing_count = int(integrity["missing_interval_count"])
    if missing_count and args.gap_policy == "reject":
        raise RuntimeError(
            "historical OHLCV range contains source gaps; rerun with --gap-policy segment "
            "to reset replay state at each continuous segment"
        )

    segments = service.contiguous_segments(candles, timeframe=timeframe)
    print(
        f"Gap policy: {args.gap_policy} missing_intervals={missing_count} "
        f"segments={len(segments)} synthetic_candles=0"
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
        f"-fee{args.fee_rate}-slip{args.slippage_bps}-gap{args.gap_policy}"
    )

    total_closed = 0
    for strategy in canonical_replay_strategies():
        if args.gap_policy == "segment":
            replay = engine.replay_segments(segments, strategy)
        else:
            replay = engine.replay(candles, strategy)
        result = store.upsert_replay(
            replay,
            dataset_run_id=dataset_run_id,
            git_commit=commit,
        )
        closed = int(replay["closed_trades"])
        total_closed += closed
        segment_detail = ""
        if args.gap_policy == "segment":
            segment_detail = (
                f" segments={replay['segment_count']}"
                f" replayed_segments={replay['replayed_segment_count']}"
                f" skipped_segments={replay['skipped_segment_count']}"
            )
        print(
            f"{strategy.strategy_id}: closed={closed} inserted={result['inserted']} "
            f"updated={result['updated']} store_total={result['total']}{segment_detail}"
        )

    historical = store.load()
    diagnostics = HistoricalResearchDiagnostics.build(historical)
    quality = ResearchFeatureDatasetProjection.quality(
        [], historical_trades=historical, source="historical"
    )
    split = ResearchFeatureDatasetProjection.temporal_split(
        [], historical_trades=historical, source="historical"
    )
    acceptance = evaluate_phase51_runtime_acceptance(
        diagnostics=diagnostics,
        quality=quality,
        split=split,
        production_position_store_mutated=False,
    )

    print(f"Total closed replay trades: {total_closed}")
    print(f"Historical research store: {store_path}")
    print(f"Research diagnostics: {json.dumps(diagnostics, sort_keys=True)}")
    print(f"Feature quality: {json.dumps(quality, sort_keys=True)}")
    print(f"Chronological split: {json.dumps(split, sort_keys=True)}")
    print(f"Phase 5.1 runtime acceptance: {json.dumps(acceptance, sort_keys=True)}")
    print("Production PositionStore mutated: False")

    if args.require_phase51_acceptance and acceptance["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
