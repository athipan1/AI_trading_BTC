from __future__ import annotations

from urllib.parse import urlparse

import pytest

from app.execution.binance_spot_protection import BinanceSpotProtectiveExitService
from app.execution.binance_spot_reconciliation import BinanceSpotProtectionReconciler
from app.execution.binance_testnet import BinanceTestnetBroker
from app.monitoring.position_store import PositionStore


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.ok = True
        self.status_code = 200

    def json(self):
        return self.payload


class Session:
    def __init__(self, orders):
        self.orders = orders

    def request(self, method, url, params=None, headers=None, timeout=None):
        path = urlparse(url).path
        if path == "/api/v3/time":
            return FakeResponse({"serverTime": 1_788_187_701_419})
        if path == "/api/v3/allOrders":
            return FakeResponse(self.orders)
        raise AssertionError(f"unexpected request: {path}")


def position_store(tmp_path) -> PositionStore:
    store = PositionStore(tmp_path / "positions.json")
    store.add_long_position(
        order_id="3489476",
        symbol="BTC/USDT",
        entry_price=77534.2,
        quantity=0.00012,
        take_profit=78483.55,
        stop_loss=77059.52,
        strategy_id="baseline",
    )
    return store


def reconciler(store: PositionStore, orders) -> BinanceSpotProtectionReconciler:
    broker = BinanceTestnetBroker("key", "secret", session=Session(orders))
    return BinanceSpotProtectionReconciler(BinanceSpotProtectiveExitService(broker), store)


def protective(
    order_id,
    client_id,
    order_type,
    status,
    price="0",
    stop="0",
    executed="0",
    quote="0",
):
    return {
        "orderId": order_id,
        "clientOrderId": client_id,
        "type": order_type,
        "status": status,
        "price": price,
        "stopPrice": stop,
        "executedQty": executed,
        "cummulativeQuoteQty": quote,
    }


def test_unprotected_position_allows_software_exit(tmp_path) -> None:
    result = reconciler(position_store(tmp_path), []).reconcile(entry_order_id="3489476")
    assert result.state == "UNPROTECTED"
    assert result.safe_to_software_exit is True
    assert result.mutation_performed is False


def test_active_oco_blocks_software_exit(tmp_path) -> None:
    orders = [
        protective(11, "protect-3489476-tp", "LIMIT_MAKER", "NEW", price="78483.55"),
        protective(12, "protect-3489476-sl", "STOP_LOSS", "NEW", stop="77059.52"),
    ]
    result = reconciler(position_store(tmp_path), orders).reconcile(entry_order_id="3489476")
    assert result.state == "PROTECTED"
    assert result.safe_to_software_exit is False


def test_filled_tp_closes_local_position(tmp_path) -> None:
    store = position_store(tmp_path)
    orders = [
        protective(
            11,
            "protect-3489476-tp",
            "LIMIT_MAKER",
            "FILLED",
            price="78483.55",
            executed="0.00012",
            quote="9.418026",
        ),
        protective(12, "protect-3489476-sl", "STOP_LOSS", "CANCELED", stop="77059.52"),
    ]
    result = reconciler(store, orders).reconcile(entry_order_id="3489476")
    saved = store.load()[0]
    assert result.state == "EXCHANGE_EXIT_RECONCILED"
    assert result.mutation_performed is True
    assert saved["status"] == "CLOSED"
    assert saved["exit_reason"] == "TP_HIT"
    assert saved["exit_order_id"] == "11"


def test_filled_tp_closes_locally_triggered_position(tmp_path) -> None:
    store = position_store(tmp_path)
    store.mark_triggered("3489476", "TP_HIT", 78483.55)
    orders = [
        protective(
            11,
            "protect-3489476-tp",
            "LIMIT_MAKER",
            "FILLED",
            price="78483.55",
            executed="0.00012",
            quote="9.418026",
        ),
        protective(12, "protect-3489476-sl", "STOP_LOSS", "CANCELED", stop="77059.52"),
    ]

    result = reconciler(store, orders).reconcile(entry_order_id="3489476")
    saved = store.load()[0]

    assert result.state == "EXCHANGE_EXIT_RECONCILED"
    assert result.safe_to_software_exit is False
    assert result.mutation_performed is True
    assert saved["status"] == "CLOSED"
    assert saved["exit_reason"] == "TP_HIT"
    assert saved["exit_order_id"] == "11"


def test_filled_sl_closes_locally_triggered_position(tmp_path) -> None:
    store = position_store(tmp_path)
    store.mark_triggered("3489476", "SL_HIT", 77059.52)
    orders = [
        protective(11, "protect-3489476-tp", "LIMIT_MAKER", "CANCELED", price="78483.55"),
        protective(
            12,
            "protect-3489476-sl",
            "STOP_LOSS",
            "FILLED",
            stop="77059.52",
            executed="0.00012",
            quote="9.2471424",
        ),
    ]

    result = reconciler(store, orders).reconcile(entry_order_id="3489476")
    saved = store.load()[0]

    assert result.state == "EXCHANGE_EXIT_RECONCILED"
    assert result.safe_to_software_exit is False
    assert result.mutation_performed is True
    assert saved["status"] == "CLOSED"
    assert saved["exit_reason"] == "SL_HIT"
    assert saved["exit_order_id"] == "12"


def test_incomplete_protection_fails_closed(tmp_path) -> None:
    orders = [
        protective(12, "protect-3489476-sl", "STOP_LOSS", "CANCELED", stop="77059.52"),
    ]
    result = reconciler(position_store(tmp_path), orders).reconcile(entry_order_id="3489476")
    assert result.state == "PROTECTION_INCOMPLETE"
    assert result.safe_to_software_exit is False


def test_multiple_filled_protective_orders_raise(tmp_path) -> None:
    orders = [
        protective(11, "protect-3489476-tp", "LIMIT_MAKER", "FILLED", price="78483.55"),
        protective(12, "protect-3489476-sl", "STOP_LOSS", "FILLED", stop="77059.52"),
    ]
    with pytest.raises(RuntimeError, match="multiple protective"):
        reconciler(position_store(tmp_path), orders).reconcile(entry_order_id="3489476")
