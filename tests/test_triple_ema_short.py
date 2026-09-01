from __future__ import annotations

from app.models import Candle, MarketRegime, TradeAction, TradeSignal
from app.risk.engine import RiskEngine
from app.strategies.triple_ema_short import TripleEMAShortStrategy


def _candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(
            timestamp_ms=index * 3_600_000,
            open=close,
            high=close + 1,
            low=max(close - 1, 0.01),
            close=close,
            volume=1,
        )
        for index, close in enumerate(closes)
    ]


def test_bearish_alignment_below_ema20_emits_short() -> None:
    strategy = TripleEMAShortStrategy()
    closes = [120.0] * 150 + [110.0] * 30 + [100.0] * 20 + [98.0]

    signal, diagnostic = strategy.analyze_with_diagnostic(
        _candles(closes),
        "BTC/USDT",
        "1h",
    )

    assert diagnostic.ema200 > diagnostic.ema50 > diagnostic.ema20
    assert diagnostic.close < diagnostic.ema20
    assert diagnostic.short_trigger is True
    assert signal.action == TradeAction.SHORT
    assert signal.regime == MarketRegime.BEAR_TREND
    assert signal.stop_loss == diagnostic.ema50
    assert signal.take_profit is not None
    assert signal.take_profit < signal.entry_price
    assert signal.risk_reward == 2.0


def test_close_above_ema50_emits_exit() -> None:
    strategy = TripleEMAShortStrategy()
    closes = [200.0] * 150 + [150.0] * 30 + [100.0] * 20 + [190.0]

    signal, diagnostic = strategy.analyze_with_diagnostic(
        _candles(closes),
        "BTC/USDT",
        "1h",
    )

    assert diagnostic.close > diagnostic.ema50
    assert diagnostic.exit_trigger is True
    assert signal.action == TradeAction.EXIT


def test_risk_engine_sizes_short_with_stop_above_entry() -> None:
    signal = TradeSignal(
        symbol="BTC/USDT",
        timeframe="1h",
        action=TradeAction.SHORT,
        confidence=0.8,
        regime=MarketRegime.BEAR_TREND,
        entry_price=100.0,
        stop_loss=110.0,
        take_profit=80.0,
        risk_reward=2.0,
    )
    decision = RiskEngine(risk_per_trade_pct=0.005).evaluate_entry(signal, equity=1000.0)

    assert decision.approved is True
    assert decision.max_loss <= 5.0
    assert decision.notional <= 250.0
