from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.execution.binance_testnet import BinanceTestnetBroker
from app.monitoring.position_store import PositionStore
from app.monitoring.spot_orphan_recovery import SpotOrphanAuditService

CONFIRM_TOKEN = "BINANCE_SPOT_TESTNET_ORPHAN_QUARANTINE"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit or explicitly quarantine a local Spot position after proven "
            "Binance Spot Testnet exchange-history discontinuity."
        )
    )
    parser.add_argument("--position-store", default="state/binance-testnet-positions.json")
    parser.add_argument("--order-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store_path = Path(args.position_store)
    store = PositionStore(store_path)
    broker = BinanceTestnetBroker(
        os.environ.get("BINANCE_TESTNET_API_KEY", ""),
        os.environ.get("BINANCE_TESTNET_API_SECRET", ""),
        max_order_notional_usdt=float(
            os.environ.get("BINANCE_TESTNET_MAX_NOTIONAL_USDT", "25")
        ),
    )
    service = SpotOrphanAuditService(broker=broker, position_store=store)
    audit = service.audit(order_id=str(args.order_id))

    if not args.apply:
        print(
            json.dumps(
                {
                    "state": (
                        "ELIGIBLE_FOR_QUARANTINE"
                        if audit["eligible_for_quarantine"]
                        else "NOT_ELIGIBLE"
                    ),
                    "mutation_performed": False,
                    **audit,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.confirm != CONFIRM_TOKEN:
        raise SystemExit(f"--apply requires --confirm {CONFIRM_TOKEN}")
    if audit["eligible_for_quarantine"] is not True:
        raise SystemExit("refusing quarantine because exchange-history proof is incomplete")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = store_path.with_name(
        store_path.name + f".before-orphan-quarantine-{stamp}.bak"
    )
    if not store_path.exists():
        raise SystemExit(f"position store does not exist: {store_path}")
    shutil.copy2(store_path, backup)

    reason = (
        "current Binance Spot Testnet account no longer exposes the entry order, "
        "entry fills, or protective-order lineage; local position quarantined "
        "without synthesizing an exchange exit or realized PnL"
    )
    position = service.quarantine(
        order_id=str(args.order_id),
        reason=reason,
        audit=audit,
    )
    print(
        json.dumps(
            {
                "state": "EXCHANGE_HISTORY_LOST",
                "mutation_performed": True,
                "backup": str(backup),
                "order_id": str(args.order_id),
                "position_status": position.get("status"),
                "reconciliation_status": position.get("reconciliation_status"),
                "exit_order_id": position.get("exit_order_id"),
                "exit_price": position.get("exit_price"),
                "gross_realized_pnl": position.get("gross_realized_pnl"),
                "net_realized_pnl": position.get("net_realized_pnl"),
                "evidence": position.get("orphaned_evidence"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
