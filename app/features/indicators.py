from __future__ import annotations

from dataclasses import dataclass

from app.models import Candle


@dataclass(frozen=True)
class IndicatorSnapshot:
    ema_fast: float
    ema_slow: float
    rsi: float
    atr: float
    momentum_pct: float


def ema(values: list[float], period: int) -> float:
    if period <= 0 or len(values) < period:
        raise ValueError("not enough values for EMA")
    seed = sum(values[:period]) / period
    multiplier = 2 / (period + 1)
    current = seed
    for value in values[period:]:
        current = (value - current) * multiplier + current
    return current


def rsi(values: list[float], period: int = 14) -> float:
    if period <= 0 or len(values) < period + 1:
        raise ValueError("not enough values for RSI")
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    window = changes[-period:]
    gains = sum(max(change, 0.0) for change in window) / period
    losses = sum(max(-change, 0.0) for change in window) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


def atr(candles: list[Candle], period: int = 14) -> float:
    if period <= 0 or len(candles) < period + 1:
        raise ValueError("not enough candles for ATR")
    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        candle = candles[i]
        prev_close = candles[i - 1].close
        true_ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - prev_close),
                abs(candle.low - prev_close),
            )
        )
    return sum(true_ranges[-period:]) / period


def compute_snapshot(
    candles: list[Candle],
    fast_period: int = 20,
    slow_period: int = 50,
    rsi_period: int = 14,
    atr_period: int = 14,
    momentum_lookback: int = 10,
) -> IndicatorSnapshot:
    required = max(slow_period, rsi_period + 1, atr_period + 1, momentum_lookback + 1)
    if len(candles) < required:
        raise ValueError(f"at least {required} candles are required")

    closes = [c.close for c in candles]
    reference = closes[-1 - momentum_lookback]
    momentum_pct = ((closes[-1] / reference) - 1) * 100
    return IndicatorSnapshot(
        ema_fast=ema(closes, fast_period),
        ema_slow=ema(closes, slow_period),
        rsi=rsi(closes, rsi_period),
        atr=atr(candles, atr_period),
        momentum_pct=momentum_pct,
    )
