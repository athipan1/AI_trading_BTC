from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.config import get_settings
from app.market_data.service import MarketDataService


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default=settings.exchange_id)
    parser.add_argument("--symbol", default=settings.symbol)
    parser.add_argument("--timeframe", default=settings.timeframe)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--output", default="data/btc_usdt_1h.csv")
    args = parser.parse_args()

    candles = MarketDataService(args.exchange).fetch_candles(args.symbol, args.timeframe, args.limit)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_ms", "open", "high", "low", "close", "volume"])
        for candle in candles:
            writer.writerow([
                candle.timestamp_ms,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
            ])
    print(output)


if __name__ == "__main__":
    main()
