"""Phase 5.7.2 research-only entry-quality policies for canonical Triple EMA signals."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from app.models import Candle, TradeAction, TradeSignal
from app.research.entry_features import build_entry_time_features
from app.research.historical_replay import ReplayStrategy


@dataclass(frozen=True)
class EntryQualityPolicy:
    """Predeclared thresholds. Never select or tune these using Phase 5.6 OOS."""

    name: str
    min_trend_strength_atr: float
    min_volume_ratio: float
    min_atr_pct: float
    max_atr_pct: float
    max_long_rsi: float
    min_short_rsi: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    def passes(self, features: dict[str, Any], *, side: str, regime: str) -> bool:
        """Use entry-time indicators exclusively; fail closed on missing features."""
        names = (
            "trend_strength_atr", "volume_ratio_20", "atr_pct", "rsi_14",
            "ema20_slope_3", "ema50_slope_3",
        )
        observed = {name: self._number(features.get(name)) for name in names}
        if any(value is None for value in observed.values()):
            return False
        trend = observed["trend_strength_atr"]
        volume = observed["volume_ratio_20"]
        atr = observed["atr_pct"]
        rsi = observed["rsi_14"]
        slope20 = observed["ema20_slope_3"]
        slope50 = observed["ema50_slope_3"]
        assert all(value is not None for value in (trend, volume, atr, rsi, slope20, slope50))
        if not (
            trend >= self.min_trend_strength_atr
            and volume >= self.min_volume_ratio
            and self.min_atr_pct <= atr <= self.max_atr_pct
        ):
            return False
        if side == "buy" and regime == "BULL_TREND":
            return slope20 > 0 and slope50 > 0 and 40 <= rsi <= self.max_long_rsi
        if side == "sell" and regime == "BEAR_TREND":
            return slope20 < 0 and slope50 < 0 and self.min_short_rsi <= rsi <= 60
        return False


# A deliberately small, pre-registered family. No OOS-driven parameter grid.
POLICIES: tuple[EntryQualityPolicy, ...] = (
    EntryQualityPolicy("balanced", 0.5, 0.7, 0.0005, 0.08, 80.0, 20.0),
    EntryQualityPolicy("confirmed", 1.2, 1.0, 0.001, 0.06, 72.0, 28.0),
)


class CandidateV2ReplayStrategy:
    """Adapter for the existing HistoricalStrategyReplay, never live execution."""

    def __init__(self, base: ReplayStrategy, policy: EntryQualityPolicy) -> None:
        self.base = base
        self.policy = policy
        self.strategy_id = f"candidate_v2_{base.strategy_id}_{policy.name}"
        self.min_candles = max(base.min_candles, 201)

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal:
        signal = self.base.analyze(candles, symbol, timeframe)
        if signal.action not in (TradeAction.BUY, TradeAction.SHORT):
            return signal  # Keep canonical exit logic intact.
        side = "buy" if signal.action == TradeAction.BUY else "sell"
        features = build_entry_time_features(candles)
        if self.policy.passes(features, side=side, regime=signal.regime.value):
            return signal
        return signal.model_copy(
            update={
                "action": TradeAction.HOLD,
                "entry_price": None,
                "stop_loss": None,
                "take_profit": None,
                "risk_reward": None,
                "reasons": [f"Phase 5.7.2 research quality filter: {self.policy.name} rejected entry"],
            }
        )