from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.integrations.hermes3d.quant_analytics import Hermes3DQuantAnalyticsProjection
from app.integrations.hermes3d.quant_performance import QuantPerformanceProjection
from app.monitoring.position_store import PositionStore


class StubAnalytics:
    def analytics(self) -> dict[str, Any]:
        return {"generated_at": "test", "data_quality": {"pnl_basis": "exchange_reconciled"}}


def _set_times(store: PositionStore, order_id: str, created_at: str, closed_at: str) -> None:
    positions = store.load()
    for item in positions:
        if str(item.get("order_id")) == order_id:
            item["created_at"] = created_at
            item["closed_at"] = closed_at
    store.save(positions)


def _reconciled_long(store: PositionStore) -> None:
    store.add_long_position(
        order_id="long-entry",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=1.0,
        take_profit=110.0,
        stop_loss=95.0,
        strategy_id="baseline",
    )
    store.mark_closed(
        "long-entry",
        exit_order_id="long-exit",
        exit_reason="TP_HIT",
        exit_price=110.0,
    )
    store.reconcile_fills(
        "long-entry",
        entry_fills={
            "order_id": "long-entry",
            "fill_count": 1,
            "filled_quantity": 1.0,
            "average_price": 101.0,
            "commission_by_asset": {"USDT": 0.1},
            "commission_quote_equivalent": 0.1,
            "realized_pnl": None,
        },
        exit_fills={
            "order_id": "long-exit",
            "fill_count": 1,
            "filled_quantity": 1.0,
            "average_price": 109.0,
            "commission_by_asset": {"USDT": 0.1},
            "commission_quote_equivalent": 0.1,
            "realized_pnl": None,
        },
        source="test",
    )
    _set_times(store, "long-entry", "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00")


def _reconciled_short(store: PositionStore) -> None:
    store.add_short_position(
        order_id="short-entry",
        symbol="BTC/USDT",
        entry_price=200.0,
        quantity=1.0,
        take_profit=180.0,
        stop_loss=205.0,
        strategy_id="triple_ema_short",
    )
    store.mark_closed(
        "short-entry",
        exit_order_id="short-exit",
        exit_reason="SL_HIT",
        exit_price=210.0,
    )
    store.reconcile_fills(
        "short-entry",
        entry_fills={
            "order_id": "short-entry",
            "fill_count": 1,
            "filled_quantity": 1.0,
            "average_price": 199.0,
            "commission_by_asset": {"USDT": 0.2},
            "commission_quote_equivalent": 0.2,
            "realized_pnl": 0.0,
        },
        exit_fills={
            "order_id": "short-exit",
            "fill_count": 1,
            "filled_quantity": 1.0,
            "average_price": 211.0,
            "commission_by_asset": {"USDT": 0.2},
            "commission_quote_equivalent": 0.2,
            "realized_pnl": -12.0,
        },
        source="test",
    )
    _set_times(store, "short-entry", "2026-01-01T01:00:00+00:00", "2026-01-01T02:00:00+00:00")


def test_quant_summary_uses_reconciled_pnl_fees_slippage_risk_and_equity(tmp_path: Path) -> None:
    spot = PositionStore(tmp_path / "spot.json")
    futures = PositionStore(tmp_path / "futures.json")
    _reconciled_long(spot)
    _reconciled_short(futures)

    summary = QuantPerformanceProjection.summarize(spot.load() + futures.load())

    assert summary["basis"] == "exchange_reconciled_closed_trades_only"
    assert summary["evaluated_trades"] == 2
    assert summary["excluded_unreconciled_trades"] == 0
    assert summary["expectancy_usdt_per_trade"] == pytest.approx(-2.3)
    assert summary["average_win_usdt"] == pytest.approx(7.8)
    assert summary["average_loss_usdt"] == pytest.approx(-12.4)
    assert summary["payoff_ratio"] == pytest.approx(7.8 / 12.4, rel=1e-6)
    assert summary["average_r_multiple"] == pytest.approx((7.8 / 6.0 + -12.4 / 6.0) / 2)
    assert summary["r_multiple_coverage_pct"] == pytest.approx(100.0)
    assert summary["r_multiple_stop_fallback_trades"] == 2
    assert summary["average_holding_seconds"] == pytest.approx(3600.0)
    assert summary["commission_usdt"] == pytest.approx(0.6)
    assert summary["fee_drag_pct_of_absolute_gross_pnl"] == pytest.approx(3.0)
    assert summary["slippage_cost_usdt"] == pytest.approx(4.0)
    assert summary["slippage_cost_coverage_pct"] == pytest.approx(100.0)
    assert summary["equity"]["ending_pnl_usdt"] == pytest.approx(-4.6)
    assert summary["equity"]["max_drawdown_usdt"] == pytest.approx(12.4)
    assert len(summary["equity"]["points"]) == 2


def test_quant_summary_excludes_unreconciled_closed_trade(tmp_path: Path) -> None:
    store = PositionStore(tmp_path / "positions.json")
    _reconciled_long(store)
    store.add_long_position(
        order_id="legacy",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=1.0,
        take_profit=110.0,
        stop_loss=95.0,
        strategy_id="baseline",
    )
    store.mark_closed(
        "legacy",
        exit_order_id="legacy-exit",
        exit_reason="TP_HIT",
        exit_price=110.0,
    )

    summary = QuantPerformanceProjection.summarize(store.load())

    assert summary["closed_trades_seen"] == 2
    assert summary["evaluated_trades"] == 1
    assert summary["excluded_unreconciled_trades"] == 1
    assert summary["expectancy_usdt_per_trade"] == pytest.approx(7.8)


def test_quant_analytics_decorates_existing_payload_and_attributes_strategies(tmp_path: Path) -> None:
    spot = PositionStore(tmp_path / "spot.json")
    futures = PositionStore(tmp_path / "futures.json")
    _reconciled_long(spot)
    _reconciled_short(futures)

    projection = Hermes3DQuantAnalyticsProjection(
        base_projection=StubAnalytics(),
        spot_position_store=spot,
        futures_position_store=futures,
    )
    payload = projection.analytics()

    assert payload["data_quality"]["pnl_basis"] == "exchange_reconciled"
    assert payload["quant_performance"]["portfolio"]["evaluated_trades"] == 2
    assert payload["quant_performance"]["strategies"]["baseline"]["evaluated_trades"] == 1
    assert payload["quant_performance"]["strategies"]["triple_ema_short"]["evaluated_trades"] == 1
    assert payload["quant_performance"]["data_quality"]["mae_mfe_available"] is False
    assert payload["quant_performance"]["data_quality"]["market_regime_available"] is False
