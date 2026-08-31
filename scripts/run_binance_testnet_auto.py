from __future__ import annotations

import argparse
import json
import os
import time

from app.auto_trading.engine import TestnetAutoTrader
from app.auto_trading.state_store import AutoTradeStateStore, AutoTradingHalted
from app.execution.binance_testnet import BinanceTestnetBroker
from app.monitoring.position_store import PositionStore
from app.notifications.line_messaging import LineMessagingNotifier
from app.risk.engine import RiskEngine
from app.strategies.baseline import BaselineStrategy

CONFIRMATION_TOKEN = "BINANCE_TESTNET_AUTO"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automatic long-only BTC trading on Binance Spot Testnet"
    )
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--entry-notional-usdt", type=float, default=None)
    parser.add_argument("--candle-limit", type=int, default=None)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=None)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--position-store", default="state/binance-testnet-positions.json")
    parser.add_argument("--state-store", default="state/binance-testnet-auto.json")
    return parser.parse_args()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _line_notifier(require_line: bool) -> LineMessagingNotifier | None:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    target_id = os.environ.get("LINE_TARGET_ID", "").strip()
    if token and target_id:
        return LineMessagingNotifier(token, target_id)
    if token or target_id:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN and LINE_TARGET_ID must both be configured")
    if require_line:
        raise ValueError("automatic trading requires LINE credentials by default")
    return None


def build_trader(args: argparse.Namespace) -> TestnetAutoTrader:
    api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
    max_notional = float(os.environ.get("BINANCE_TESTNET_MAX_NOTIONAL_USDT", "25"))
    max_exit_notional = float(os.environ.get("BINANCE_TESTNET_MAX_EXIT_NOTIONAL_USDT", "100"))
    entry_notional = args.entry_notional_usdt
    if entry_notional is None:
        entry_notional = float(os.environ.get("BTC_TESTNET_AUTO_ENTRY_NOTIONAL_USDT", "10"))
    candle_limit = args.candle_limit
    if candle_limit is None:
        candle_limit = int(os.environ.get("BTC_TESTNET_AUTO_CANDLE_LIMIT", "120"))

    broker = BinanceTestnetBroker(
        api_key=api_key,
        api_secret=api_secret,
        max_order_notional_usdt=max_notional,
        max_exit_notional_usdt=max_exit_notional,
    )
    require_line = _env_bool("BTC_TESTNET_AUTO_REQUIRE_LINE", True)
    notifier = _line_notifier(require_line)
    risk_engine = RiskEngine(
        risk_per_trade_pct=float(os.environ.get("RISK_PER_TRADE_PCT", "0.005")),
        max_position_notional_pct=float(
            os.environ.get("MAX_POSITION_NOTIONAL_PCT", "0.25")
        ),
        min_reward_risk=float(os.environ.get("MIN_REWARD_RISK", "1.5")),
    )
    return TestnetAutoTrader(
        broker=broker,
        strategy=BaselineStrategy(),
        risk_engine=risk_engine,
        position_store=PositionStore(args.position_store),
        state_store=AutoTradeStateStore(args.state_store),
        notifier=notifier,
        symbol=args.symbol,
        timeframe=args.timeframe,
        entry_notional_usdt=entry_notional,
        candle_limit=candle_limit,
    )


def main() -> None:
    args = parse_args()
    if args.confirm != CONFIRMATION_TOKEN:
        raise SystemExit(f"automatic trading requires --confirm {CONFIRMATION_TOKEN}")

    interval_seconds = args.interval_seconds
    if interval_seconds is None:
        interval_seconds = int(os.environ.get("BTC_TESTNET_AUTO_INTERVAL_SECONDS", "30"))
    if interval_seconds < 10:
        raise SystemExit("automatic trading interval must be at least 10 seconds")

    trader = build_trader(args)
    preflight = trader.broker.preflight(trader.symbol)
    print(json.dumps({"event": "PREFLIGHT_OK", "preflight": preflight}, sort_keys=True))
    if trader.notifier is not None:
        trader.notifier.send_text(
            "\n".join(
                [
                    "Trading BTC",
                    "🤖 Binance Spot Testnet Auto Trading เริ่มทำงาน",
                    f"คู่: {trader.symbol}",
                    f"Timeframe: {trader.timeframe}",
                    f"Entry cap: {trader.entry_notional_usdt:.2f} USDT",
                ]
            )
        )

    while True:
        try:
            result = trader.run_once()
            print(json.dumps(result, sort_keys=True))
        except AutoTradingHalted as exc:
            print(
                json.dumps(
                    {
                        "event": "AUTO_TRADING_HALTED",
                        "reason": str(exc),
                        "state": trader.state_store.load(),
                    },
                    sort_keys=True,
                )
            )
            raise SystemExit(2) from exc
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "CHECK_ERROR",
                        "error": f"{exc.__class__.__name__}: {exc}",
                    },
                    sort_keys=True,
                )
            )
            if not args.watch:
                raise

        if not args.watch:
            break
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
