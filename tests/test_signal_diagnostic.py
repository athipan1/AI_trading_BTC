from __future__ import annotations

from app.models import Candle, TradeAction
from app.notifications.line_messaging import format_signal_diagnostic_message
from app.strategies.baseline import BaselineStrategy


def make_candles(*, rising: bool) -> list[Candle]:
    candles: list[Candle] = []
    for index in range(60):
        close = 100.0 + index if rising else 100.0
        candles.append(
            Candle(
                timestamp_ms=(index + 1) * 3_600_000,
                open=close - 0.25,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=10.0,
            )
        )
    return candles


def test_diagnostic_reports_all_four_buy_gates() -> None:
    strategy = BaselineStrategy()

    signal, diagnostic = strategy.analyze_with_diagnostic(
        make_candles(rising=True),
        "BTC/USDT",
        "1h",
    )

    assert signal.action == TradeAction.BUY
    assert diagnostic.buy_ready is True
    assert diagnostic.ema_trend_ok is True
    assert diagnostic.price_above_ema_fast_ok is True
    assert diagnostic.rsi_ok is True
    assert diagnostic.momentum_ok is True
    assert diagnostic.blockers == ()
    assert diagnostic.atr > 0


def test_diagnostic_explains_why_flat_market_is_not_buy() -> None:
    strategy = BaselineStrategy()

    signal, diagnostic = strategy.analyze_with_diagnostic(
        make_candles(rising=False),
        "BTC/USDT",
        "1h",
    )

    assert signal.action == TradeAction.HOLD
    assert diagnostic.buy_ready is False
    assert diagnostic.ema_trend_ok is False
    assert diagnostic.price_above_ema_fast_ok is False
    assert diagnostic.rsi_ok is True
    assert diagnostic.momentum_ok is False
    assert len(diagnostic.blockers) == 3


def test_line_diagnostic_contains_values_checks_and_blockers() -> None:
    message = format_signal_diagnostic_message(
        symbol="BTC/USDT",
        timeframe="1h",
        candle_ms=123456789,
        signal_action="HOLD",
        regime="SIDEWAYS",
        price=100.0,
        ema_fast=101.0,
        ema_slow=100.5,
        ema_bull_threshold=100.701,
        rsi=48.0,
        momentum_pct=-0.25,
        atr=2.5,
        ema_trend_ok=False,
        price_above_ema_fast_ok=False,
        rsi_ok=False,
        momentum_ok=False,
        buy_ready=False,
        blockers=["RSI 48.00 must be >= 50"],
    )

    assert "Signal Diagnostic" in message
    assert "Price: 100.00 USDT" in message
    assert "EMA20: 101.00" in message
    assert "EMA50: 100.50" in message
    assert "RSI14: 48.00" in message
    assert "Momentum(10): -0.2500%" in message
    assert "ATR14: 2.50" in message
    assert "❌ RSI >= 50" in message
    assert "เหตุผลที่ยังไม่ BUY" in message
    assert "RSI 48.00 must be >= 50" in message
