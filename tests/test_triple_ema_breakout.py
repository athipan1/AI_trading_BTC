from __future__ import annotations

from app.models import Candle, TradeAction
from app.strategies.triple_ema_breakout import TripleEMAAlignmentBreakoutStrategy


def _candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(
            timestamp_ms=(index + 1) * 3_600_000,
            open=close,
            high=close + 1.0,
            low=max(0.01, close - 1.0),
            close=close,
            volume=10.0,
        )
        for index, close in enumerate(closes)
    ]


def test_first_alignment_bar_is_buy() -> None:
    strategy = TripleEMAAlignmentBreakoutStrategy()
    closes = [100.0] * 200 + [110.0]

    signal, diagnostic = strategy.analyze_with_diagnostic(
        _candles(closes),
        "BTC/USDT",
        "1h",
    )

    assert signal.action == TradeAction.BUY
    assert diagnostic.current_alignment is True
    assert diagnostic.previous_alignment is False
    assert diagnostic.first_trigger is True
    assert signal.take_profit is None
    assert signal.stop_loss == diagnostic.ema50


def test_alignment_does_not_buy_again_on_next_bar() -> None:
    strategy = TripleEMAAlignmentBreakoutStrategy()
    closes = [100.0] * 200 + [110.0, 111.0]

    signal, diagnostic = strategy.analyze_with_diagnostic(
        _candles(closes),
        "BTC/USDT",
        "1h",
    )

    assert diagnostic.current_alignment is True
    assert diagnostic.previous_alignment is True
    assert diagnostic.first_trigger is False
    assert signal.action == TradeAction.HOLD


def test_close_below_ema50_is_exit() -> None:
    strategy = TripleEMAAlignmentBreakoutStrategy()
    closes = [100.0 + (index * 0.1) for index in range(200)] + [80.0]

    signal, diagnostic = strategy.analyze_with_diagnostic(
        _candles(closes),
        "BTC/USDT",
        "1h",
    )

    assert diagnostic.exit_trigger is True
    assert signal.action == TradeAction.EXIT
    assert signal.stop_loss == diagnostic.ema50
