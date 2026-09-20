from __future__ import annotations

import argparse
import json
import os

from app.execution.binance_spot_protection import BinanceSpotProtectiveExitService
from app.execution.binance_testnet import BinanceTestnetBroker
from app.monitoring.position_store import PositionStore

CONFIRMATION_TOKEN = "BINANCE_TESTNET_PROTECT"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit or attach exchange-side OCO protection to a tracked Spot Testnet long."
    )
    parser.add_argument("--position-store", default="state/binance-testnet-positions.json")
    parser.add_argument("--order-id", required=True)
    parser.add_argument("--mode", choices=("audit", "protect"), default="audit")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = PositionStore(args.position_store)
    positions = [
        item
        for item in store.load()
        if item.get("status") == "OPEN" and str(item.get("order_id")) == str(args.order_id)
    ]
    if len(positions) != 1:
        raise SystemExit("expected exactly one matching OPEN tracked position")
    position = positions[0]
    if str(position.get("side", "")).lower() != "buy":
        raise SystemExit("Spot protective OCO currently supports long positions only")
    if position.get("take_profit") is None:
        raise SystemExit("tracked position has no fixed take-profit")

    broker = BinanceTestnetBroker(
        os.environ.get("BINANCE_TESTNET_API_KEY", ""),
        os.environ.get("BINANCE_TESTNET_API_SECRET", ""),
        max_order_notional_usdt=float(os.environ.get("BINANCE_TESTNET_MAX_NOTIONAL_USDT", "25")),
    )
    service = BinanceSpotProtectiveExitService(broker)
    audit = service.audit(symbol=str(position["symbol"]), entry_order_id=str(position["order_id"]))

    if args.mode == "audit":
        print(json.dumps(audit, indent=2, sort_keys=True))
        return 0

    if args.confirm != CONFIRMATION_TOKEN:
        raise SystemExit(f"protect requires --confirm {CONFIRMATION_TOKEN}")
    if audit["protected"]:
        print(json.dumps(audit, indent=2, sort_keys=True))
        return 0

    result = service.place_oco(
        symbol=str(position["symbol"]),
        entry_order_id=str(position["order_id"]),
        quantity=float(position["quantity"]),
        take_profit=float(position["take_profit"]),
        stop_loss=float(position["stop_loss"]),
    )
    print(
        json.dumps(
            {
                "order_list_id": result.order_list_id,
                "symbol": result.symbol,
                "quantity": result.quantity,
                "take_profit": result.take_profit,
                "stop_loss": result.stop_loss,
                "status": result.status,
                "exchange_side_protection": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
