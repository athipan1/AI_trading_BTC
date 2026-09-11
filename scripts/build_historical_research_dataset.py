from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime

from app.config import get_settings
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
    parser.add_argument("--since", required=True, help="UTC date, for example 2026-07-01")
    parser.add_argument("--until", required=True, help="UTC exclusive end date")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--quantity", type=float, default=0.001)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--store", default=None)
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

    print(f"Total closed replay trades: {total_closed}")
    print(f"Historical research store: {store_path}")
    print("Production PositionStore mutated: False")


if __name__ == "__main__":
    main()
