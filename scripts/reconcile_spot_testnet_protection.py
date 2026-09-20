from __future__ import annotations

import argparse
import json
import os

from app.execution.binance_spot_protection import BinanceSpotProtectiveExitService
from app.execution.binance_spot_reconciliation import BinanceSpotProtectionReconciler
from app.execution.binance_testnet import BinanceTestnetBroker
from app.monitoring.position_store import PositionStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile Binance Spot Testnet protective exits.")
    parser.add_argument("--position-store", default="state/binance-testnet-positions.json")
    parser.add_argument("--order-id", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Allow local PositionStore closure when a filled exchange protective exit is proven.",
    )
    args = parser.parse_args()

    store = PositionStore(args.position_store)
    broker = BinanceTestnetBroker(
        os.environ.get("BINANCE_TESTNET_API_KEY", ""),
        os.environ.get("BINANCE_TESTNET_API_SECRET", ""),
        max_order_notional_usdt=float(os.environ.get("BINANCE_TESTNET_MAX_NOTIONAL_USDT", "25")),
    )
    reconciler = BinanceSpotProtectionReconciler(
        BinanceSpotProtectiveExitService(broker),
        store,
    )

    if not args.apply:
        before = store.load()
        result = reconciler.reconcile(entry_order_id=args.order_id)
        after = store.load()
        if result.mutation_performed:
            store.save(before)
            payload = {
                **result.__dict__,
                "mutation_performed": False,
                "dry_run_would_mutate": True,
            }
        else:
            payload = {**result.__dict__, "dry_run_would_mutate": False}
        if after != before and not result.mutation_performed:
            raise RuntimeError("dry-run detected an unexpected PositionStore mutation")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    result = reconciler.reconcile(entry_order_id=args.order_id)
    print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
