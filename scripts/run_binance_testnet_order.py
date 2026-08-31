from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.execution.binance_testnet import BinanceTestnetBroker

CONFIRMATION_TOKEN = "BINANCE_TESTNET"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Binance Spot Testnet preflight/order runner")
    parser.add_argument("--mode", choices=("preflight", "place_order"), default="preflight")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--side", choices=("buy", "sell"), default="buy")
    parser.add_argument("--notional-usdt", type=float, default=10.0)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--report", default="reports/binance-testnet-order.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
    max_notional = float(os.environ.get("BINANCE_TESTNET_MAX_NOTIONAL_USDT", "25"))

    if args.mode == "place_order" and args.confirm != CONFIRMATION_TOKEN:
        raise SystemExit(f"place_order requires --confirm {CONFIRMATION_TOKEN}")

    broker = BinanceTestnetBroker(
        api_key=api_key,
        api_secret=api_secret,
        max_order_notional_usdt=max_notional,
    )
    if args.mode == "preflight":
        result = broker.preflight(args.symbol)
    else:
        result = broker.place_market_order(args.symbol, args.side, args.notional_usdt)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
