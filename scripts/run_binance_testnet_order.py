from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.execution.binance_testnet import BinanceTestnetBroker
from app.monitoring.position_store import PositionStore
from app.notifications.line_messaging import LineMessagingNotifier, format_open_order_message

CONFIRMATION_TOKEN = "BINANCE_TESTNET"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Binance Spot Testnet preflight/order runner")
    parser.add_argument("--mode", choices=("preflight", "place_order"), default="preflight")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--side", choices=("buy", "sell"), default="buy")
    parser.add_argument("--notional-usdt", type=float, default=10.0)
    parser.add_argument("--tp-pct", type=float, default=None)
    parser.add_argument("--sl-pct", type=float, default=None)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--report", default="reports/binance-testnet-order.json")
    parser.add_argument("--position-store", default="state/binance-testnet-positions.json")
    return parser.parse_args()


def _alert_percentages(args: argparse.Namespace) -> tuple[float, float]:
    tp_pct = args.tp_pct
    sl_pct = args.sl_pct
    if tp_pct is None:
        tp_pct = float(os.environ.get("BTC_TESTNET_TP_PCT", "2"))
    if sl_pct is None:
        sl_pct = float(os.environ.get("BTC_TESTNET_SL_PCT", "1"))
    if tp_pct <= 0:
        raise ValueError("TP percentage must be positive")
    if sl_pct <= 0 or sl_pct >= 100:
        raise ValueError("SL percentage must be greater than 0 and less than 100")
    return tp_pct, sl_pct


def _line_notifier_from_env() -> LineMessagingNotifier | None:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    target_id = os.environ.get("LINE_TARGET_ID", "").strip()
    if not token and not target_id:
        return None
    if not token or not target_id:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN and LINE_TARGET_ID must both be configured")
    return LineMessagingNotifier(token, target_id)


def _enrich_buy_result(
    result: dict,
    broker: BinanceTestnetBroker,
    args: argparse.Namespace,
) -> None:
    order_id = result.get("order_id")
    entry_price = result.get("average")
    quantity = result.get("filled")
    if order_id is None or not entry_price or not quantity:
        result["tracking_status"] = "skipped_missing_fill_data"
        return

    tp_pct, sl_pct = _alert_percentages(args)
    take_profit = float(entry_price) * (1 + tp_pct / 100)
    stop_loss = float(entry_price) * (1 - sl_pct / 100)
    store = PositionStore(args.position_store)
    store.add_long_position(
        order_id=str(order_id),
        symbol=args.symbol,
        entry_price=float(entry_price),
        quantity=float(quantity),
        take_profit=take_profit,
        stop_loss=stop_loss,
    )
    tracked_positions = store.count_active()
    snapshot = broker.account_snapshot(args.symbol)

    result["take_profit"] = take_profit
    result["stop_loss"] = stop_loss
    result["tp_pct"] = tp_pct
    result["sl_pct"] = sl_pct
    result["account"] = snapshot
    result["tracked_positions"] = tracked_positions
    result["tracking_status"] = "active"

    notifier = _line_notifier_from_env()
    if notifier is None:
        result["line_notification"] = "not_configured"
        return

    message = format_open_order_message(
        symbol=args.symbol.upper(),
        order_id=str(order_id),
        side="buy",
        account_balance_usdt=float(snapshot["quote_total"]),
        estimated_portfolio_value_usdt=float(snapshot["estimated_portfolio_value_quote"]),
        entry_price=float(entry_price),
        lot=float(quantity),
        take_profit=take_profit,
        stop_loss=stop_loss,
        binance_open_orders=int(snapshot["open_orders_count"]),
        tracked_positions=tracked_positions,
    )
    notifier.send_text(message)
    result["line_notification"] = "sent"


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
        if args.side == "buy":
            try:
                _enrich_buy_result(result, broker, args)
            except Exception as exc:  # order is already submitted; never encourage a blind retry
                result["post_order_status"] = "warning"
                result["post_order_error"] = f"{exc.__class__.__name__}: {exc}"
        else:
            result["tracking_status"] = "not_applicable_for_sell"

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
