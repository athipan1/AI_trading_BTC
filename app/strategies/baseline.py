from __future__ import annotations

from app.features.indicators import compute_snapshot
from app.models import Candle, MarketRegime, TradeAction, TradeSignal


class BaselineStrategy:
    """Long-only Phase 1 strategy. EXIT closes an existing paper position; it never shorts."""

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal:
        snapshot = compute_snapshot(candles)
        price = candles[-1].close

        if snapshot.ema_fast > snapshot.ema_slow * 1.002:
            regime = MarketRegime.BULL_TREND
        elif snapshot.ema_fast < snapshot.ema_slow * 0.998:
            regime = MarketRegime.BEAR_TREND
        else:
            regime = MarketRegime.SIDEWAYS

        bullish = (
            regime == MarketRegime.BULL_TREND
            and price > snapshot.ema_fast
            and snapshot.rsi >= 50
            and snapshot.momentum_pct > 0
        )
        bearish_exit = (
            regime == MarketRegime.BEAR_TREND
            or (price < snapshot.ema_fast and snapshot.momentum_pct < 0)
        )

        if bullish:
            stop = price - (1.5 * snapshot.atr)
            risk = price - stop
            take_profit = price + (2.0 * risk)
            confidence = min(
                0.95,
                0.55
                + min(max(snapshot.momentum_pct, 0), 5) / 25
                + min(max(snapshot.rsi - 50, 0), 30) / 150,
            )
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.BUY,
                confidence=round(confidence, 4),
                regime=regime,
                entry_price=price,
                stop_loss=stop,
                take_profit=take_profit,
                risk_reward=2.0,
                reasons=[
                    "EMA20 above EMA50",
                    "price above EMA20",
                    "positive momentum",
                    f"RSI={snapshot.rsi:.2f}",
                ],
            )

        if bearish_exit:
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.EXIT,
                confidence=0.7,
                regime=regime,
                reasons=["bearish trend or momentum invalidated"],
            )

        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            action=TradeAction.HOLD,
            confidence=0.5,
            regime=regime,
            reasons=["entry conditions not aligned"],
        )
