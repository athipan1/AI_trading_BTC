from __future__ import annotations

from pathlib import Path

import pytest

from app.integrations.hermes3d.analytics import Hermes3DTradingAnalyticsProjection
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.monitoring.position_store import PositionStore


def build_projection(tmp_path: Path) -> Hermes3DTradingAnalyticsProjection:
    return Hermes3DTradingAnalyticsProjection(
        journal=Hermes3DEventJournal(tmp_path / "events.jsonl"),
        spot_position_store=PositionStore(tmp_path / "spot.json"),
        futures_position_store=PositionStore(tmp_path / "futures.json"),
        auto_state_paths={},
    )


def test_analytics_prefers_reconciled_net_pnl_and_reports_full_coverage(tmp_path: Path) -> None:
    projection = build_projection(tmp_path)
    store = projection.spot_position_store
    store.add_long_position(
        order_id="entry",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=0.1,
        take_profit=120.0,
        stop_loss=90.0,
    )
    store.mark_closed(
        "entry",
        exit_order_id="exit",
        exit_reason="TP_HIT",
        exit_price=120.0,
    )
    store.reconcile_fills(
        "entry",
        entry_fills={
            "order_id": "entry",
            "fill_count": 1,
            "filled_quantity": 0.1,
            "average_price": 101.0,
            "commission_by_asset": {"USDT": 0.02},
            "commission_quote_equivalent": 0.02,
            "realized_pnl": None,
        },
        exit_fills={
            "order_id": "exit",
            "fill_count": 1,
            "filled_quantity": 0.1,
            "average_price": 119.0,
            "commission_by_asset": {"USDT": 0.02},
            "commission_quote_equivalent": 0.02,
            "realized_pnl": None,
        },
        source="test",
    )

    analytics = projection.analytics()

    assert analytics["portfolio"]["realized_pnl_usdt"] == pytest.approx(1.76)
    assert analytics["portfolio"]["estimated_realized_pnl_usdt"] == pytest.approx(1.76)
    assert analytics["portfolio"]["reconciled_trades"] == 1
    assert analytics["portfolio"]["estimated_trades"] == 0
    assert analytics["portfolio"]["commission_usdt"] == pytest.approx(0.04)
    assert analytics["data_quality"]["pnl_basis"] == "exchange_reconciled"
    assert analytics["data_quality"]["fees_included"] is True
    assert analytics["data_quality"]["exchange_fill_reconciliation"] is True
    assert analytics["data_quality"]["reconciliation_coverage_pct"] == pytest.approx(100.0)


def test_analytics_keeps_legacy_estimate_fallback_for_unreconciled_positions(tmp_path: Path) -> None:
    projection = build_projection(tmp_path)
    store = projection.spot_position_store
    store.add_long_position(
        order_id="legacy",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=0.1,
        take_profit=120.0,
        stop_loss=90.0,
    )
    store.mark_closed(
        "legacy",
        exit_order_id="legacy-exit",
        exit_reason="TP_HIT",
        exit_price=120.0,
    )

    analytics = projection.analytics()

    assert analytics["portfolio"]["realized_pnl_usdt"] == pytest.approx(2.0)
    assert analytics["portfolio"]["estimated_trades"] == 1
    assert analytics["data_quality"]["pnl_basis"] == "entry_exit_estimate"
    assert analytics["data_quality"]["fees_included"] is False
    assert analytics["data_quality"]["reconciliation_coverage_pct"] == 0.0
