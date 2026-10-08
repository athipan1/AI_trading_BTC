from __future__ import annotations

from pathlib import Path

import pytest

from app.monitoring.position_store import PositionStore
from app.monitoring.spot_orphan_recovery import SpotOrphanAuditService


class FakeBroker:
    def __init__(
        self,
        *,
        entry_order_exists: bool = False,
        entry_fill_exists: bool = False,
        protective_order_exists: bool = False,
    ) -> None:
        self.entry_order_exists = entry_order_exists
        self.entry_fill_exists = entry_fill_exists
        self.protective_order_exists = protective_order_exists

    @staticmethod
    def _symbol_parts(symbol: str) -> tuple[str, str, str]:
        assert symbol == "BTC/USDT"
        return "BTCUSDT", "BTC", "USDT"

    def _request(self, method, path, params=None, signed=False):
        assert method == "GET"
        if path == "/api/v3/order":
            if self.entry_order_exists:
                return {
                    "orderId": int(params["orderId"]),
                    "symbol": "BTCUSDT",
                    "status": "FILLED",
                }
            raise RuntimeError(
                "Binance Testnet API error HTTP 400: "
                "code=-2013 msg=Order does not exist."
            )

        if path == "/api/v3/myTrades":
            if self.entry_fill_exists:
                return [
                    {
                        "id": 1,
                        "orderId": int(params["orderId"]),
                        "price": "86629.86",
                        "qty": "0.00011",
                        "quoteQty": "9.5292846",
                    }
                ]
            return []

        if path == "/api/v3/allOrders":
            rows = []
            if self.entry_order_exists:
                rows.append(
                    {
                        "orderId": 9324710,
                        "clientOrderId": "entry-9324710",
                        "status": "FILLED",
                    }
                )
            if self.protective_order_exists:
                rows.append(
                    {
                        "orderId": 9324800,
                        "clientOrderId": "protect-9324710-sl",
                        "status": "CANCELED",
                    }
                )
            return rows

        if path == "/api/v3/openOrders":
            if self.protective_order_exists:
                return [
                    {
                        "orderId": 9324801,
                        "clientOrderId": "protect-9324710-tp",
                        "status": "NEW",
                    }
                ]
            return []

        raise AssertionError(f"unexpected request path: {path}")

    def account_snapshot(self, symbol: str) -> dict:
        assert symbol == "BTC/USDT"
        return {
            "base_total": 1.0,
            "quote_total": 10_000.0,
            "reference_price": 83_030.45,
            "open_orders_count": 0,
        }


def local_store(tmp_path: Path) -> PositionStore:
    store = PositionStore(tmp_path / "positions.json")
    position = store.add_long_position(
        order_id="9324710",
        symbol="BTC/USDT",
        entry_price=86_629.86,
        quantity=0.00011,
        take_profit=87_439.84,
        stop_loss=86_224.86,
        strategy_id="baseline",
        exit_mode="fixed_tp_sl",
    )
    store.reconcile_fills(
        "9324710",
        entry_fills={
            "order_id": "9324710",
            "average_price": 86_629.86,
            "filled_quantity": 0.00011,
            "fill_count": 1,
            "commission_by_asset": {},
            "commission_quote_equivalent": 0.0,
        },
        exit_fills=None,
        source="historical_test_fixture",
    )
    store.mark_triggered(position["order_id"], "SL_HIT", 86_218.0)
    return store


def test_orphan_audit_requires_complete_exchange_history_absence(tmp_path: Path) -> None:
    store = local_store(tmp_path)
    service = SpotOrphanAuditService(
        broker=FakeBroker(),  # type: ignore[arg-type]
        position_store=store,
    )

    audit = service.audit(order_id="9324710")

    assert audit["eligible_for_quarantine"] is True
    assert audit["checks"] == {
        "local_unresolved": True,
        "fixed_tp_sl": True,
        "no_recorded_exit": True,
        "no_realized_pnl": True,
        "entry_order_not_found": True,
        "entry_order_absent_from_history": True,
        "entry_fills_absent": True,
        "protective_history_absent": True,
        "open_protective_orders_absent": True,
    }
    evidence = audit["evidence"]
    assert evidence["entry_order_lookup"] == "NOT_FOUND"
    assert evidence["entry_fill_count"] == 0
    assert evidence["protective_history_count"] == 0
    assert evidence["account_snapshot"]["base_total"] == 1.0


@pytest.mark.parametrize(
    "broker",
    [
        FakeBroker(entry_order_exists=True),
        FakeBroker(entry_fill_exists=True),
        FakeBroker(protective_order_exists=True),
    ],
)
def test_orphan_audit_refuses_when_exchange_lineage_still_exists(
    tmp_path: Path,
    broker: FakeBroker,
) -> None:
    store = local_store(tmp_path)
    service = SpotOrphanAuditService(
        broker=broker,  # type: ignore[arg-type]
        position_store=store,
    )

    audit = service.audit(order_id="9324710")

    assert audit["eligible_for_quarantine"] is False
    with pytest.raises(RuntimeError, match="not eligible"):
        service.quarantine(
            order_id="9324710",
            reason="must not quarantine while exchange lineage exists",
            audit=audit,
        )


def test_orphan_quarantine_preserves_entry_audit_without_fake_close(tmp_path: Path) -> None:
    store = local_store(tmp_path)
    service = SpotOrphanAuditService(
        broker=FakeBroker(),  # type: ignore[arg-type]
        position_store=store,
    )
    audit = service.audit(order_id="9324710")

    position = service.quarantine(
        order_id="9324710",
        reason="current testnet account no longer exposes historical exchange lineage",
        audit=audit,
    )

    assert position["status"] == "ORPHANED"
    assert position["reconciliation_status"] == "EXCHANGE_HISTORY_LOST"
    assert position["entry_fill_price"] == 86_629.86
    assert position["exit_order_id"] is None
    assert position["exit_price"] is None
    assert position["gross_realized_pnl"] is None
    assert position["net_realized_pnl"] is None
    assert position["closed_at"] is None
    assert position["orphaned_evidence"]["entry_order_lookup"] == "NOT_FOUND"
