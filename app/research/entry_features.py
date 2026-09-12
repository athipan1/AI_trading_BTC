# ruff: noqa: I001
from __future__ import annotations

import math
import statistics
from typing import Final

from app.features.indicators import atr, ema, rsi
from app.models import Candle


ENTRY_FEATURE_SCHEMA_VERSION: Final[str] = "entry_feature_schema_v1"

ADVANCED_ENTRY_NUMERIC_FEATURES: Final[tuple[str, ...]] = (
    "decision_close",
    "rsi_14",
    "atr_14",
    "atr_pct",
    "ema20_distance_pct",
    "ema50_distance_pct",
    "ema200_distance_pct",
    "ema20_50_spread_pct",
    "ema50_200_spread_pct",
    "ema20_slope_3",
    "ema50_slope_3",
    "ema200_slope_3",
    "return_1h",
    "return_3h",
    "return_6h",
    "return_24h",
    "log_return_1h",
    "rolling_volatility_24h",
    "volume_ratio_20",
    "volume_zscore_20",
    "candle_body_pct",
    "candle_range_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "close_location",
    "trend_strength_atr",
)


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def _return(closes: list[float], lookback: int) -> float | None:
    if lookback <= 0 or len(closes) <= lookback:
        return None
    reference = closes[-1 - lookback]
    return _safe_div(closes[-1] - reference, reference)


def _ema_slope(closes: list[float], period: int, lookback: int = 3) -> float | None:
    if len(closes) < period + lookback:
        return None
    current = ema(closes, period)
    previous = ema(closes[:-lookback], period)
    return _safe_div(current - previous, previous)


def _rolling_log_volatility(closes: list[float], lookback: int = 24) -> float | None:
    if len(closes) < lookback + 1:
        return None
    window = closes[-(lookback + 1) :]
    log_returns = [math.log(window[index] / window[index - 1]) for index in range(1, len(window))]
    if not log_returns:
        return None
    value = statistics.pstdev(log_returns)
    return value if math.isfinite(value) else None


def build_entry_time_features(candles: list[Candle]) -> dict[str, float | None]:
    """Build causal features using only candles available at the decision timestamp."""
    if len(candles) < 200:
        raise ValueError("at least 200 candles are required for entry-time features")

    decision = candles[-1]
    closes = [candle.close for candle in candles]
    volumes = [candle.volume for candle in candles]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    atr14 = atr(candles, 14)
    rsi14 = rsi(closes, 14)

    volume_window = volumes[-20:]
    volume_mean = sum(volume_window) / len(volume_window)
    volume_std = statistics.pstdev(volume_window)
    volume_ratio = _safe_div(decision.volume, volume_mean)
    volume_zscore = _safe_div(decision.volume - volume_mean, volume_std) if volume_std > 0 else 0.0

    candle_range = decision.high - decision.low
    body = abs(decision.close - decision.open)
    upper_wick = decision.high - max(decision.open, decision.close)
    lower_wick = min(decision.open, decision.close) - decision.low

    return {
        "decision_close": decision.close,
        "rsi_14": rsi14,
        "atr_14": atr14,
        "atr_pct": _safe_div(atr14, decision.close),
        "ema20_distance_pct": _safe_div(decision.close - ema20, decision.close),
        "ema50_distance_pct": _safe_div(decision.close - ema50, decision.close),
        "ema200_distance_pct": _safe_div(decision.close - ema200, decision.close),
        "ema20_50_spread_pct": _safe_div(ema20 - ema50, decision.close),
        "ema50_200_spread_pct": _safe_div(ema50 - ema200, decision.close),
        "ema20_slope_3": _ema_slope(closes, 20),
        "ema50_slope_3": _ema_slope(closes, 50),
        "ema200_slope_3": _ema_slope(closes, 200),
        "return_1h": _return(closes, 1),
        "return_3h": _return(closes, 3),
        "return_6h": _return(closes, 6),
        "return_24h": _return(closes, 24),
        "log_return_1h": math.log(closes[-1] / closes[-2]),
        "rolling_volatility_24h": _rolling_log_volatility(closes, 24),
        "volume_ratio_20": volume_ratio,
        "volume_zscore_20": volume_zscore,
        "candle_body_pct": _safe_div(body, decision.close),
        "candle_range_pct": _safe_div(candle_range, decision.close),
        "upper_wick_pct": _safe_div(upper_wick, candle_range),
        "lower_wick_pct": _safe_div(lower_wick, candle_range),
        "close_location": _safe_div(decision.close - decision.low, candle_range),
        "trend_strength_atr": _safe_div(abs(ema20 - ema200), atr14),
    }
