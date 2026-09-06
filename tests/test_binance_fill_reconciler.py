from __future__ import annotations

import pytest

from app.monitoring.binance_fill_reconciler import aggregate_binance_fills
from app.monitoring.position_store import PositionStore


def test_aggregate_spot_fills_uses_weighted_average_and_converts_base_fee() -> None:
    summary = aggregate_binance_fills(
        [
            {
                "id": 1,
                "orderId": 42,
                "price": "100",
                "qty": "0.1",
                "quoteQty": "10",
                "commission": "0.001",
                "commissionAsset": "BTC",
            },
            {
                "id": 2,
                "orderId": 42,
                "price": "102",
                "qty": "0.2",
                "quoteQty": "20.4",
                "commission": "0.02",
                "commissionAsset": "USDT",
            },
        ],
        order_id="42",
        base_asset="BTC",
        quote_asset="USDT",
    )

    assert summary.fill_count == 2
    assert summary.filled_quantity == pytest.approx(0.3)
    assert summary.quote_quantity == pytest.approx(30.4)
    assert summary.average_price == pytest.approx(30.4 / 0.3)
    assert summary.commission_by_asset == {"BTC": pytest.approx(0.001), "USDT": pytest.approx(0.02)}
    assert summary.commission_quote_equivalent == pytest.approx(0.12)
    assert summary.commission_quote_complete is True
    assert summary.trade_ids == ["1", "2"]


def test_aggregate_marks_third_asset_commission_incomplete() -> None:
    summary = aggregate_binance_fills(
        [
            {
                "id": 1,
                "orderId": 7,
                "price": "100",
                "qty": "0.1",
                "quoteQty": "10",
                "commission": "0.01",
                "commissionAsset": "BNB",
            }
        ],
        order_id="7",
        base_asset="BTC",
        quote_asset="USDT",
    )

    assert summary.commission_quote_complete is False
    assert summary.commission_quote_equivalent is None


def test_reconcile_closed_position_is_idempotent_and_computes_net_pnl(tmp_path) -> None:
    store = PositionStore(tmp_path / "positions.json")
    store.add_long_position(
        order_id="entry-1",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=0.1,
        take_profit=110.0,
        stop_loss=95.0,
    )
    store.mark_closed(
        "entry-1",
        exit_order_id="exit-1",
        exit_reason="TP_HIT",
        exit_price=110.0,
    )

    entry = {
        "order_id": "entry-1",
        "fill_count": 2,
        "filled_quantity": 0.1,
        "average_price": 100.5,
        "commission_by_asset": {"USDT": 0.01},
        "commission_quote_equivalent": 0.01,
        "realized_pnl": None,
    }
    exit_fill = {
        "order_id": "exit-1",
        "fill_count": 1,
        "filled_quantity": 0.1,
        "average_price": 109.5,
        "commission_by_asset": {"USDT": 0.01},
        "commission_quote_equivalent": 0.01,
        "realized_pnl": None,
    }

    first = store.reconcile_fills(
        "entry-1",
        entry_fills=entry,
        exit_fills=exit_fill,
        source="test",
    )
    second = store.reconcile_fills(
        "entry-1",
        entry_fills=entry,
        exit_fills=exit_fill,
        source="test",
    )

    assert first["reconciliation_status"] == "RECONCILED"
    assert first["entry_fill_price"] == pytest.approx(100.5)
    assert first["exit_fill_price"] == pytest.approx(109.5)
    assert first["gross_realized_pnl"] == pytest.approx(0.9)
    assert first["net_realized_pnl"] == pytest.approx(0.88)
    assert second["net_realized_pnl"] == pytest.approx(first["net_realized_pnl"])
    assert len(store.load()) == 1


def test_futures_exchange_realized_pnl_takes_precedence(tmp_path) -> None:
    store = PositionStore(tmp_path / "futures.json")
    store.add_short_position(
        order_id="short-entry",
        symbol="BTC/USDT",
        entry_price=200.0,
        quantity=0.1,
        take_profit=180.0,
        stop_loss=210.0,
    )
    store.mark_closed(
        "short-entry",
        exit_order_id="short-exit",
        exit_reason="TP_HIT",
        exit_price=180.0,
    )

    reconciled = store.reconcile_fills(
        "short-entry",
        entry_fills={
            "order_id": "short-entry",
            "fill_count": 1,
            "filled_quantity": 0.1,
            "average_price": 200.0,
            "commission_by_asset": {"USDT": 0.02},
            "commission_quote_equivalent": 0.02,
            "realized_pnl": 0.0,
        },
        exit_fills={
            "order_id": "short-exit",
            "fill_count": 1,
            "filled_quantity": 0.1,
            "average_price": 181.0,
            "commission_by_asset": {"USDT": 0.02},
            "commission_quote_equivalent": 0.02,
            "realized_pnl": 1.75,
        },
        source="futures-test",
    )

    assert reconciled["realized_pnl_basis"] == "binance_realized_pnl"
    assert reconciled["gross_realized_pnl"] == pytest.approx(1.75)
    assert reconciled["net_realized_pnl"] == pytest.approx(1.71)
