from __future__ import annotations

from pathlib import Path

import pytest

from app.integrations.hermes3d.quant_performance import QuantPerformanceProjection
from app.monitoring.position_store import PositionStore
from app.monitoring.trade_path_observer import TradePathObserver


def _reconcile_long(store: PositionStore, order_id: str, exit_order_id: str) -> None:
    store.reconcile_fills(
        order_id,
        entry_fills={
            "order_id": order_id,
            "fill_count": 1,
            "filled_quantity": 0.1,
            "average_price": 100.0,
            "commission_by_asset": {"USDT": 0.02},
            "commission_quote_equivalent": 0.02,
            "realized_pnl": None,
        },
        exit_fills={
            "order_id": exit_order_id,
            "fill_count": 1,
            "filled_quantity": 0.1,
            "average_price": 110.0,
            "commission_by_asset": {"USDT": 0.02},
            "commission_quote_equivalent": 0.02,
            "realized_pnl": None,
        },
        source="test",
    )


def test_trade_path_observer_persists_entry_context_and_extrema(tmp_path: Path) -> None:
    store = PositionStore(tmp_path / "positions.json")
    position = store.add_long_position(
        order_id="entry",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=0.1,
        take_profit=120.0,
        stop_loss=90.0,
        strategy_id="baseline",
    )
    observer = TradePathObserver(store)

    observer.capture_result(
        {
            "event": "BUY_FILLED",
            "position": position,
            "signal": {"regime": "BULL_TREND"},
        }
    )
    observer.observe_open_positions("BTC/USDT", 120.0)
    observer.observe_open_positions("BTC/USDT", 95.0)

    tracked = store.load()[0]
    assert tracked["initial_stop_loss"] == pytest.approx(90.0)
    assert tracked["initial_stop_loss_source"] == "entry_snapshot"
    assert tracked["entry_market_regime"] == "BULL_TREND"
    assert tracked["trade_path_highest_price"] == pytest.approx(120.0)
    assert tracked["trade_path_lowest_price"] == pytest.approx(95.0)
    assert tracked["trade_path_observation_count"] == 2
    assert tracked["trade_path_basis"] == "runner_live_price_samples"


def test_quant_performance_calculates_mae_mfe_and_regime_attribution(tmp_path: Path) -> None:
    store = PositionStore(tmp_path / "positions.json")
    position = store.add_long_position(
        order_id="entry",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=0.1,
        take_profit=120.0,
        stop_loss=90.0,
        strategy_id="baseline",
    )
    observer = TradePathObserver(store)
    observer.capture_result(
        {
            "event": "BUY_FILLED",
            "position": position,
            "signal": {"regime": "BULL_TREND"},
        }
    )
    observer.observe_open_positions("BTC/USDT", 120.0)
    observer.observe_open_positions("BTC/USDT", 95.0)
    store.mark_closed(
        "entry",
        exit_order_id="exit",
        exit_reason="TP_HIT",
        exit_price=110.0,
    )
    _reconcile_long(store, "entry", "exit")

    positions = store.load()
    summary = QuantPerformanceProjection.summarize(positions)
    regimes = QuantPerformanceProjection.by_market_regime(positions)
    quality = QuantPerformanceProjection.data_availability(positions)

    assert summary["average_mfe_usdt"] == pytest.approx(2.0)
    assert summary["average_mae_usdt"] == pytest.approx(-0.5)
    assert summary["average_mfe_r"] == pytest.approx(2.0)
    assert summary["average_mae_r"] == pytest.approx(-0.5)
    assert summary["mae_mfe_coverage_pct"] == pytest.approx(100.0)
    assert regimes["BULL_TREND"]["evaluated_trades"] == 1
    assert quality["initial_stop_loss_coverage_pct"] == pytest.approx(100.0)
    assert quality["mae_mfe_available"] is True
    assert quality["mae_mfe_coverage_pct"] == pytest.approx(100.0)
    assert quality["market_regime_available"] is True
    assert quality["market_regime_coverage_pct"] == pytest.approx(100.0)


def test_short_excursion_uses_inverse_price_direction() -> None:
    position = {
        "order_id": "short",
        "strategy_id": "triple_ema_short",
        "status": "CLOSED",
        "reconciliation_status": "RECONCILED",
        "side": "sell",
        "entry_fill_price": 100.0,
        "entry_filled_quantity": 0.1,
        "initial_stop_loss": 110.0,
        "initial_stop_loss_source": "entry_snapshot",
        "trade_path_highest_price": 105.0,
        "trade_path_lowest_price": 80.0,
        "net_realized_pnl": 1.0,
        "gross_realized_pnl": 1.0,
        "entry_commission_quote_equivalent": 0.0,
        "exit_commission_quote_equivalent": 0.0,
    }

    summary = QuantPerformanceProjection.summarize([position])

    assert summary["average_mfe_usdt"] == pytest.approx(2.0)
    assert summary["average_mae_usdt"] == pytest.approx(-0.5)
    assert summary["average_mfe_r"] == pytest.approx(2.0)
    assert summary["average_mae_r"] == pytest.approx(-0.5)


def test_legacy_trades_remain_explicitly_unavailable_for_path_metrics() -> None:
    legacy = {
        "order_id": "legacy",
        "status": "CLOSED",
        "reconciliation_status": "RECONCILED",
        "side": "buy",
        "entry_fill_price": 100.0,
        "entry_filled_quantity": 0.1,
        "stop_loss": 90.0,
        "net_realized_pnl": 1.0,
        "gross_realized_pnl": 1.0,
        "entry_commission_quote_equivalent": 0.0,
        "exit_commission_quote_equivalent": 0.0,
    }

    summary = QuantPerformanceProjection.summarize([legacy])
    quality = QuantPerformanceProjection.data_availability([legacy])

    assert summary["mae_mfe_coverage_pct"] == 0.0
    assert summary["average_mae_r"] is None
    assert summary["average_mfe_r"] is None
    assert quality["mae_mfe_available"] is False
    assert quality["market_regime_available"] is False
