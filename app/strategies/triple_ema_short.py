from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.features.indicators import ema
from app.models import Candle, MarketRegime, TradeAction, TradeSignal


@dataclass(frozen=True)
class TripleEMAShortDiagnostic:
    close: float
    ema20: float
    ema50: float
    ema200: float
    bearish_alignment: bool
    short_trigger: bool
    exit_trigger: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TripleEMAShortStrategy:
    """Bearish Triple EMA strategy for USD-M Futures demo trading."""

    strategy_id = "triple_ema_short"
    exit_mode = "close_above_ema50"
    min_candles = 201

    @staticmethod
    def _bearish_alignment(close: float, ema20: float, ema50: float, ema200: float) -> bool:
        return ema200 > ema50 > ema20 and close < ema20

    def analyze_with_diagnostic(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
    ) -> tuple[TradeSignal, TripleEMAShortDiagnostic]:
        if len(candles) < self.min_candles:
            raise ValueError(f"Triple EMA SHORT requires at least {self.min_candles} closed candles")

        closes = [candle.close for candle in candles]
        close = closes[-1]
        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)
        ema200 = ema(closes, 200)
        bearish_alignment = self._bearish_alignment(close, ema20, ema50, ema200)
        exit_trigger = close > ema50

        diagnostic = TripleEMAShortDiagnostic(
            close=close,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            bearish_alignment=bearish_alignment,
            short_trigger=bearish_alignment,
            exit_trigger=exit_trigger,
        )

        if bearish_alignment:
            return (
                TradeSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    action=TradeAction.SHORT,
                    confidence=0.8,
                    regime=MarketRegime.BEAR_TREND,
                    entry_price=close,
                    stop_loss=ema50,
                    take_profit=None,
                    risk_reward=None,
                    reasons=[
                        "EMA200 > EMA50 > EMA20",
                        "closed 1h candle below EMA20",
                        "EMA50 is initial risk reference and close-based exit",
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
                    regime=MarketRegime.SIDEWAYS,
                    stop_loss=ema50,
                    reasons=["closed 1h candle above current EMA50"],
                ),
                diagnostic,
            )

        return (
            TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.HOLD,
                confidence=0.5,
                regime=(
                    MarketRegime.BEAR_TREND
                    if ema20 < ema50 < ema200
                    else MarketRegime.SIDEWAYS
                ),
                stop_loss=ema50,
                reasons=["waiting for bearish alignment or EMA50 close-based exit"],
            ),
            diagnostic,
        )

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal:
        signal, _ = self.analyze_with_diagnostic(candles, symbol, timeframe)
        return signal
