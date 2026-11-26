"""Phase 5.7.5 conservative H1 execution replay and accounting regression tests."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.models import Candle, MarketRegime, TradeAction, TradeSignal
from app.research.execution_realism import ExecutionRealismConfig, ExecutionRealismReplay

HOUR = 3_600_000


def bar(
    index: int, *, open: float = 100, high: float = 101, low: float = 99,
    close: float = 100,
) -> Candle:
    return Candle(timestamp_ms=index * HOUR, open=open, high=high, low=low, close=close, volume=3)


class FixedSignal:
    strategy_id = "stub"
    min_candles = 2

    def __init__(
        self, *, side: str = "buy", stop: float = 95, target: float | None = 110,
        exit_at_history: int | None = None,
    ) -> None:
        self.side = side
        self.stop = stop
        self.target = target
        self.exit_at_history = exit_at_history
        self.calls: list[int] = []

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal:
        self.calls.append(candles[-1].timestamp_ms)
        action = (
            TradeAction.BUY if self.side == "buy" else TradeAction.SHORT
        ) if len(candles) == 2 else (
            TradeAction.EXIT if self.exit_at_history == len(candles) else TradeAction.HOLD
        )
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            action=action,
            confidence=1,
            regime=MarketRegime.BULL_TREND if self.side == "buy" else MarketRegime.BEAR_TREND,
            entry_price=100 if action != TradeAction.EXIT else None,
            stop_loss=self.stop,
            take_profit=self.target,
        )


def replay(bars: list[Candle], strategy: FixedSignal, *, config: ExecutionRealismConfig | None = None):
    return ExecutionRealismReplay(config or ExecutionRealismConfig(
        quantity=1, fee_rate=0, slippage_bps=0, stop_extra_slippage_bps=0,
        gap_extra_slippage_bps=0,
    )).replay(bars, strategy)


def test_stop_hit_with_recovered_h1_close_is_loss_and_entry_next_open() -> None:
    bars = [bar(0), bar(1), bar(2, low=94, high=105, close=101), bar(3)]
    strategy = FixedSignal()
    result = replay(bars, strategy)
    assert result["closed_trades"] == 1
    trade = result["trades"][0]
    assert trade["exit_reason"] == "STOP_INTRABAR"
    assert trade["entry_fill_price"] == 100
    assert trade["initial_stop_loss"] == 95
    assert trade["exit_fill_price"] == 95
    assert trade["realized_r"] == -1.0
    assert trade["decision_at"] == datetime.fromtimestamp(HOUR / 1000, tz=UTC).isoformat()
    assert trade["opened_at_ms"] == 2 * HOUR
    assert strategy.calls[0] == HOUR
    assert result["trade_execution"] is False


def test_same_candle_stop_tp_is_stop_first_not_made_up_winner() -> None:
    result = replay([bar(0), bar(1), bar(2, low=94, high=115), bar(3)], FixedSignal())
    assert result["closed_trades"] == 1
    assert result["ambiguous_sl_tp_bars"] == 1
    trade = result["trades"][0]
    assert trade["intrabar_sl_tp_ambiguous"] is True
    assert trade["exit_reason"] == "STOP_INTRABAR"
    assert trade["realized_r"] == -1.0


def test_short_profit_target_hit_before_close() -> None:
    result = replay(
        [bar(0), bar(1), bar(2, high=104, low=89), bar(3)],
        FixedSignal(side="sell", stop=105, target=90),
    )
    trade = result["trades"][0]
    assert trade["exit_reason"] == "TAKE_PROFIT_INTRABAR"
    assert trade["realized_r"] == 2.0


def test_long_gap_stop_executes_at_worse_next_open() -> None:
    result = replay(
        [bar(0), bar(1), bar(2), bar(3, open=90, high=91, low=89, close=90), bar(4)],
        FixedSignal(stop=95, target=120),
    )
    trade = result["trades"][0]
    assert trade["exit_reason"] == "STOP_GAP"
    assert trade["exit_fill_price"] == 90
    assert trade["realized_r"] == -2.0
    assert result["stop_gap_exits"] == 1


def test_strategy_exit_never_fills_before_next_candle() -> None:
    bars = [bar(0), bar(1), bar(2), bar(3), bar(4, open=102, high=103, low=101, close=102)]
    result = replay(bars, FixedSignal(stop=90, target=None, exit_at_history=4))
    trade = result["trades"][0]
    assert trade["exit_reason"] == "STRATEGY_EXIT"
    assert trade["closed_at"] == datetime.fromtimestamp(4 * HOUR / 1000, tz=UTC).isoformat()
    assert trade["exit_fill_price"] == 102


def test_fee_slippage_and_stop_shock_are_in_net_realized_r() -> None:
    cfg = ExecutionRealismConfig(
        quantity=1, fee_rate=0.001, slippage_bps=2,
        stop_extra_slippage_bps=3, gap_extra_slippage_bps=5,
    )
    out = replay([bar(0), bar(1), bar(2, high=104, low=94), bar(3)], FixedSignal(), config=cfg)
    trade = out["trades"][0]
    entry = 100 * 1.0002
    exit_fill = 95 * (1 - .0005)
    expected = (exit_fill - entry - .001 * entry - .001 * exit_fill) / (entry - 95)
    assert math.isclose(trade["entry_fill_price"], entry)
    assert math.isclose(trade["exit_fill_price"], exit_fill)
    assert math.isclose(trade["realized_r"], expected)
    assert trade["funding_assumption_usdt"] == 0


def test_worst_gap_stop_slippage_adds_gap_shock() -> None:
    cfg = ExecutionRealismConfig(
        quantity=1, fee_rate=0, slippage_bps=0, stop_extra_slippage_bps=0,
        gap_extra_slippage_bps=20,
    )
    out = replay(
        [bar(0), bar(1), bar(2), bar(3, open=90, high=91, low=89, close=90), bar(4)],
        FixedSignal(), config=cfg,
    )
    assert out["trades"][0]["exit_fill_price"] == pytest.approx(90 * (1 - .002))


def test_invalid_entry_bracket_is_rejected_not_assumed_safe() -> None:
    result = replay([bar(0), bar(1), bar(2), bar(3)], FixedSignal(stop=101))
    assert result["closed_trades"] == 0
    assert result["rejected_unsafe_entries"] == 1


def test_open_positions_not_force_closed_or_fabricated() -> None:
    out = replay([bar(0), bar(1), bar(2), bar(3)], FixedSignal(stop=90, target=120))
    assert out["open_trade_excluded"] is True
    assert out["closed_trades"] == 0


def test_futures_funding_only_static_sensitivity_when_explicit() -> None:
    cfg = ExecutionRealismConfig(
        venue="futures", quantity=1, fee_rate=0, slippage_bps=0,
        stop_extra_slippage_bps=0, gap_extra_slippage_bps=0, funding_rate_per_8h=0.001,
    )
    bars = [bar(i) for i in range(13)]
    out = replay(bars, FixedSignal(stop=90, target=None, exit_at_history=11), config=cfg)
    trade = out["trades"][0]
    assert trade["holding_seconds"] == 9 * 3600
    assert trade["funding_intervals"] == 1
    assert trade["funding_assumption_usdt"] == pytest.approx(0.1)
    assert trade["net_realized_pnl"] == pytest.approx(-0.1)
    assert out["funding_basis"] == "STATIC_SENSITIVITY_NOT_REAL_HISTORY"
    with pytest.raises(ValueError, match="spot trading"):
        replace(cfg, venue="spot")


def test_invalid_ohlcv_and_gap_fail_closed() -> None:
    engine = ExecutionRealismReplay()
    with pytest.raises(ValueError, match="OHLC range"):
        engine.replay([bar(0), bar(1), bar(2, low=102)], FixedSignal())
    with pytest.raises(ValueError, match="bar gap"):
        engine.replay([bar(0), bar(1), bar(4)], FixedSignal())
    with pytest.raises(ValueError, match="more than"):
        engine.replay([bar(0), bar(1)], FixedSignal())


def test_gap_aware_segments_reset_positions_without_synthetic_bars() -> None:
    out = ExecutionRealismReplay(ExecutionRealismConfig(
        quantity=1, fee_rate=0, slippage_bps=0,
        stop_extra_slippage_bps=0, gap_extra_slippage_bps=0,
    )).replay_segments([
        [bar(0), bar(1), bar(2)],
        [bar(5), bar(6), bar(7, low=94), bar(8)],
    ], FixedSignal())
    assert out["closed_trades"] == 1
    assert out["segment_count"] == 2
    assert out["trades"][0]["opened_at_ms"] == 7 * HOUR


def test_config_rejects_nonfinite_and_invalid_funding() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        ExecutionRealismConfig(fee_rate=float("nan"))
    with pytest.raises(ValueError, match="slippage"):
        ExecutionRealismConfig(slippage_bps=-1)
    with pytest.raises(ValueError, match="funding sensitivity"):
        ExecutionRealismConfig(venue="futures", funding_rate_per_8h=0.05)