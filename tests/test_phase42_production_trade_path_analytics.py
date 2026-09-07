from __future__ import annotations

from pathlib import Path

import pytest

from app.integrations.hermes3d.quant_performance import QuantPerformanceProjection
from app.monitoring.position_store import PositionStore
from app.monitoring.trade_path_observer import TradePathObserver


def test_entry_context_is_immutable_and_captures_initial_risk(tmp_path: Path) -> None:
    store = PositionStore(tmp_path / "positions.json")
    position = store.add_long_position(
        order_id="entry-1",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=0.2,
        take_profit=120.0,
        stop_loss=90.0,
        strategy_id="triple_ema",
    )
    observer = TradePathObserver(store)

    observer.capture_result(
        {
            "event": "BUY_FILLED",
            "position": position,
            "signal": {"regime": "BULL_TREND"},
        }
    )
    first = store.load()[0]
    captured_at = first["entry_context_captured_at"]

    store.update_stop_loss("entry-1", 95.0)
    observer.observe_open_positions("BTC/USDT", 108.0)
    observer.capture_result(
        {
            "event": "BUY_FILLED",
            "position": position,
            "signal": {"regime": "SIDEWAYS"},
        }
    )

    tracked = store.load()[0]
    assert tracked["initial_stop_loss"] == pytest.approx(90.0)
    assert tracked["initial_risk_price_distance"] == pytest.approx(10.0)
    assert tracked["initial_risk_usdt"] == pytest.approx(2.0)
    assert tracked["initial_risk_source"] == "entry_snapshot"
    assert tracked["entry_market_regime"] == "BULL_TREND"
    assert tracked["entry_context_captured_at"] == captured_at
    assert tracked["trade_path_highest_price"] == pytest.approx(108.0)
    assert tracked["trade_path_lowest_price"] == pytest.approx(100.0)


def _closed_trade(
    *,
    order_id: str,
    strategy_id: str,
    regime: str,
    side: str,
    entry: float,
    stop: float,
    high: float,
    low: float,
    pnl: float,
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "strategy_id": strategy_id,
        "status": "CLOSED",
        "reconciliation_status": "RECONCILED",
        "side": side,
        "entry_fill_price": entry,
        "entry_filled_quantity": 0.1,
        "initial_stop_loss": stop,
        "initial_stop_loss_source": "entry_snapshot",
        "initial_risk_price_distance": abs(entry - stop),
        "initial_risk_usdt": abs(entry - stop) * 0.1,
        "initial_risk_source": "entry_snapshot",
        "entry_market_regime": regime,
        "trade_path_highest_price": high,
        "trade_path_lowest_price": low,
        "net_realized_pnl": pnl,
        "gross_realized_pnl": pnl,
        "entry_commission_quote_equivalent": 0.0,
        "exit_commission_quote_equivalent": 0.0,
    }


def test_strategy_market_regime_segmentation_preserves_long_and_short_edge() -> None:
    positions = [
        _closed_trade(
            order_id="long-trend",
            strategy_id="triple_ema",
            regime="BULL_TREND",
            side="buy",
            entry=100.0,
            stop=90.0,
            high=120.0,
            low=95.0,
            pnl=1.5,
        ),
        _closed_trade(
            order_id="long-sideways",
            strategy_id="triple_ema",
            regime="SIDEWAYS",
            side="buy",
            entry=100.0,
            stop=90.0,
            high=104.0,
            low=91.0,
            pnl=-0.5,
        ),
        _closed_trade(
            order_id="short-trend",
            strategy_id="triple_ema_short",
            regime="BEAR_TREND",
            side="sell",
            entry=100.0,
            stop=110.0,
            high=105.0,
            low=80.0,
            pnl=1.2,
        ),
    ]

    segmented = QuantPerformanceProjection.by_strategy_and_market_regime(positions)
    quality = QuantPerformanceProjection.data_availability(positions)

    assert segmented["triple_ema"]["BULL_TREND"]["evaluated_trades"] == 1
    assert segmented["triple_ema"]["BULL_TREND"]["average_mfe_r"] == pytest.approx(2.0)
    assert segmented["triple_ema"]["SIDEWAYS"]["average_mae_r"] == pytest.approx(-0.9)
    assert segmented["triple_ema_short"]["BEAR_TREND"]["average_mfe_r"] == pytest.approx(2.0)
    assert segmented["triple_ema_short"]["BEAR_TREND"]["average_mae_r"] == pytest.approx(-0.5)
    assert quality["initial_risk_snapshot_coverage_pct"] == pytest.approx(100.0)
    assert quality["mae_mfe_coverage_pct"] == pytest.approx(100.0)
    assert quality["market_regime_coverage_pct"] == pytest.approx(100.0)
