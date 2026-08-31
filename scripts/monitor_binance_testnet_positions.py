from __future__ import annotations

import argparse
import json
import os
import time

from app.execution.binance_testnet import BinanceTestnetBroker
from app.monitoring.position_store import PositionStore
from app.notifications.line_messaging import LineMessagingNotifier, format_level_hit_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor Binance Testnet TP/SL alert levels")
    parser.add_argument("--position-store", default="state/binance-testnet-positions.json")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=30)
    return parser.parse_args()


def build_services(
    args: argparse.Namespace,
) -> tuple[BinanceTestnetBroker, LineMessagingNotifier, PositionStore]:
    api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
    line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    line_target = os.environ.get("LINE_TARGET_ID", "")
    max_notional = float(os.environ.get("BINANCE_TESTNET_MAX_NOTIONAL_USDT", "25"))
    broker = BinanceTestnetBroker(api_key, api_secret, max_order_notional_usdt=max_notional)
    notifier = LineMessagingNotifier(line_token, line_target)
    return broker, notifier, PositionStore(args.position_store)


def check_once(
    broker: BinanceTestnetBroker,
    notifier: LineMessagingNotifier,
    store: PositionStore,
) -> list[dict]:
    events: list[dict] = []
    positions = store.load()
    prices: dict[str, float] = {}

    for position in positions:
        if position.get("status") != "OPEN":
            continue
        symbol = str(position["symbol"])
        price = prices.setdefault(symbol, broker.current_price(symbol))
        take_profit = float(position["take_profit"])
        stop_loss = float(position["stop_loss"])
        event = None
        if price >= take_profit:
            event = "TP_HIT"
        elif price <= stop_loss:
            event = "SL_HIT"
        if event:
            store.mark_triggered(str(position["order_id"]), event, price)
            events.append(
                {
                    "order_id": str(position["order_id"]),
                    "symbol": symbol,
                    "event": event,
                    "hit_price": price,
                }
            )

    for position in store.pending_notifications():
        symbol = str(position["symbol"])
        snapshot = broker.account_snapshot(symbol)
        tracked_positions = store.count_active()
        message = format_level_hit_message(
            event=str(position["status"]),
            symbol=symbol,
            order_id=str(position["order_id"]),
            account_balance_usdt=float(snapshot["quote_total"]),
            estimated_portfolio_value_usdt=float(snapshot["estimated_portfolio_value_quote"]),
            entry_price=float(position["entry_price"]),
            hit_price=float(position["hit_price"]),
            lot=float(position["quantity"]),
            take_profit=float(position["take_profit"]),
            stop_loss=float(position["stop_loss"]),
            binance_open_orders=int(snapshot["open_orders_count"]),
            tracked_positions=tracked_positions,
        )
        notifier.send_text(message)
        store.mark_notification_sent(str(position["order_id"]))

    return events


def main() -> None:
    args = parse_args()
    if args.interval_seconds < 5:
        raise SystemExit("--interval-seconds must be at least 5")
    broker, notifier, store = build_services(args)

    try:
        while True:
            events = check_once(broker, notifier, store)
            print(json.dumps({"events": events, "tracked_positions": store.count_active()}))
            if not args.watch:
                break
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print("TP/SL monitor stopped")


if __name__ == "__main__":
    main()
