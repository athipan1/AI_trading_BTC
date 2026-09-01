from __future__ import annotations

import pytest

from app.models import MarketRegime, TradeAction, TradeSignal
from app.monitoring.position_store import PositionStore
from app.risk.engine import RiskEngine


def test_position_store_allows_one_position_per_strategy(tmp_path) -> None:
    store = PositionStore(tmp_path / "positions.json")

    baseline = store.add_long_position(
        order_id="1001",
        strategy_id="baseline",
        exit_mode="fixed_tp_sl",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=0.1,
        take_profit=104.0,
        stop_loss=98.0,
    )
    triple = store.add_long_position(
        order_id="1002",
        strategy_id="triple_ema",
        exit_mode="close_below_ema50",
        symbol="BTC/USDT",
        entry_price=101.0,
        quantity=0.1,
        take_profit=None,
        stop_loss=99.0,
    )

    assert baseline["strategy_id"] == "baseline"
    assert triple["strategy_id"] == "triple_ema"
    assert store.count_active() == 2
    assert len(store.active_positions("BTC/USDT", strategy_id="baseline")) == 1
    assert len(store.active_positions("BTC/USDT", strategy_id="triple_ema")) == 1

    with pytest.raises(ValueError):
        store.add_long_position(
            order_id="1003",
            strategy_id="baseline",
            exit_mode="fixed_tp_sl",
            symbol="BTC/USDT",
            entry_price=102.0,
            quantity=0.1,
            take_profit=106.0,
            stop_loss=100.0,
        )


def test_risk_engine_accepts_dynamic_exit_strategy_without_fixed_tp() -> None:
    signal = TradeSignal(
        symbol="BTC/USDT",
        timeframe="1h",
        action=TradeAction.BUY,
        confidence=0.8,
        regime=MarketRegime.BULL_TREND,
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=None,
        risk_reward=None,
        reasons=["EMA50 dynamic exit"],
    )

    decision = RiskEngine(risk_per_trade_pct=0.005).evaluate_entry(signal, equity=1000.0)

    assert decision.approved is True
    assert decision.max_loss <= 5.0 + 1e-9
