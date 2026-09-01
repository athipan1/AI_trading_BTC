from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.features.indicators import ema
from app.models import Candle, MarketRegime, TradeAction, TradeSignal


@dataclass(frozen=True)
class TripleEMADiagnostic:
    close: float
    ema20: float
    ema50: float
    ema200: float
    current_alignment: bool
    previous_alignment: bool
    first_trigger: bool
    exit_trigger: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TripleEMAAlignmentBreakoutStrategy:
    """Long-only first-trigger Triple EMA trend strategy with EMA50 close-based exit."""

    strategy_id = "triple_ema"
    exit_mode = "close_below_ema50"
    min_candles = 201

    @staticmethod
    def _alignment(close: float, ema20: float, ema50: float, ema200: float) -> bool:
        return ema20 > ema50 and ema50 > ema200 and close > ema20

    @staticmethod
    def _regime(ema20: float, ema50: float, ema200: float) -> MarketRegime:
        if ema20 > ema50 > ema200:
            return MarketRegime.BULL_TREND
        if ema20 < ema50 < ema200:
            return MarketRegime.BEAR_TREND
        return MarketRegime.SIDEWAYS

    def analyze_with_diagnostic(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
    ) -> tuple[TradeSignal, TripleEMADiagnostic]:
        if len(candles) < self.min_candles:
            raise ValueError(f"Triple EMA strategy requires at least {self.min_candles} closed candles")

        closes = [candle.close for candle in candles]
        previous_closes = closes[:-1]

        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)
        ema200 = ema(closes, 200)
        prev_ema20 = ema(previous_closes, 20)
        prev_ema50 = ema(previous_closes, 50)
        prev_ema200 = ema(previous_closes, 200)

        close = closes[-1]
        previous_close = closes[-2]
        current_alignment = self._alignment(close, ema20, ema50, ema200)
        previous_alignment = self._alignment(
            previous_close,
            prev_ema20,
            prev_ema50,
            prev_ema200,
        )
        first_trigger = current_alignment and not previous_alignment
        exit_trigger = close < ema50
        regime = self._regime(ema20, ema50, ema200)

        diagnostic = TripleEMADiagnostic(
            close=close,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            current_alignment=current_alignment,
            previous_alignment=previous_alignment,
            first_trigger=first_trigger,
            exit_trigger=exit_trigger,
        )

        if first_trigger:
            return (
                TradeSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    action=TradeAction.BUY,
                    confidence=0.8,
                    regime=regime,
                    entry_price=close,
                    stop_loss=ema50,
                    take_profit=None,
                    risk_reward=None,
                    reasons=[
                        "first bar with EMA20 > EMA50 > EMA200",
                        "close above EMA20",
                        "EMA50 is initial risk reference and dynamic close-based exit",
                    ],
                ),
                diagnostic,
            )

        if exit_trigger:
            return (
                TradeSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    action=TradeAction.EXIT,
                    confidence=0.9,
                    regime=regime,
                    stop_loss=ema50,
                    reasons=["closed 1h candle below current EMA50"],
                ),
                diagnostic,
            )

        return (
            TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.HOLD,
                confidence=0.5,
                regime=regime,
                stop_loss=ema50,
                reasons=["waiting for first alignment trigger or EMA50 close-based exit"],
            ),
            diagnostic,
        )

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal:
        signal, _ = self.analyze_with_diagnostic(candles, symbol, timeframe)
        return signal
