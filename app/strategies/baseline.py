from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.features.indicators import IndicatorSnapshot, compute_snapshot
from app.models import Candle, MarketRegime, TradeAction, TradeSignal


@dataclass(frozen=True)
class SignalDiagnostic:
    """Human-readable evaluation of the exact BaselineStrategy BUY gates."""

    price: float
    ema_fast: float
    ema_slow: float
    ema_bull_threshold: float
    rsi: float
    momentum_pct: float
    atr: float
    regime: MarketRegime
    ema_trend_ok: bool
    price_above_ema_fast_ok: bool
    rsi_ok: bool
    momentum_ok: bool
    buy_ready: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["regime"] = self.regime.value
        payload["blockers"] = list(self.blockers)
        return payload


class BaselineStrategy:
    """Long-only Phase 1 strategy. EXIT closes an existing paper position; it never shorts."""

    EMA_BULL_BUFFER = 1.002
    EMA_BEAR_BUFFER = 0.998
    RSI_ENTRY_MIN = 50.0

    @classmethod
    def _regime(cls, snapshot: IndicatorSnapshot) -> MarketRegime:
        if snapshot.ema_fast > snapshot.ema_slow * cls.EMA_BULL_BUFFER:
            return MarketRegime.BULL_TREND
        if snapshot.ema_fast < snapshot.ema_slow * cls.EMA_BEAR_BUFFER:
            return MarketRegime.BEAR_TREND
        return MarketRegime.SIDEWAYS

    @classmethod
    def _diagnostic(
        cls,
        *,
        snapshot: IndicatorSnapshot,
        price: float,
    ) -> SignalDiagnostic:
        regime = cls._regime(snapshot)
        ema_threshold = snapshot.ema_slow * cls.EMA_BULL_BUFFER
        ema_trend_ok = regime == MarketRegime.BULL_TREND
        price_ok = price > snapshot.ema_fast
        rsi_ok = snapshot.rsi >= cls.RSI_ENTRY_MIN
        momentum_ok = snapshot.momentum_pct > 0

        blockers: list[str] = []
        if not ema_trend_ok:
            blockers.append(
                f"EMA20 {snapshot.ema_fast:.2f} must be above "
                f"EMA50 x 1.002 ({ema_threshold:.2f})"
            )
        if not price_ok:
            blockers.append(
                f"price {price:.2f} must be above EMA20 {snapshot.ema_fast:.2f}"
            )
        if not rsi_ok:
            blockers.append(f"RSI {snapshot.rsi:.2f} must be >= {cls.RSI_ENTRY_MIN:.0f}")
        if not momentum_ok:
            blockers.append(f"momentum {snapshot.momentum_pct:.4f}% must be > 0%")

        return SignalDiagnostic(
            price=price,
            ema_fast=snapshot.ema_fast,
            ema_slow=snapshot.ema_slow,
            ema_bull_threshold=ema_threshold,
            rsi=snapshot.rsi,
            momentum_pct=snapshot.momentum_pct,
            atr=snapshot.atr,
            regime=regime,
            ema_trend_ok=ema_trend_ok,
            price_above_ema_fast_ok=price_ok,
            rsi_ok=rsi_ok,
            momentum_ok=momentum_ok,
            buy_ready=not blockers,
            blockers=tuple(blockers),
        )

    def analyze_with_diagnostic(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
    ) -> tuple[TradeSignal, SignalDiagnostic]:
        snapshot = compute_snapshot(candles)
        price = candles[-1].close
        diagnostic = self._diagnostic(snapshot=snapshot, price=price)

        bearish_exit = (
            diagnostic.regime == MarketRegime.BEAR_TREND
            or (price < snapshot.ema_fast and snapshot.momentum_pct < 0)
        )

        if diagnostic.buy_ready:
            stop = price - (1.5 * snapshot.atr)
            risk = price - stop
            take_profit = price + (2.0 * risk)
            confidence = min(
                0.95,
                0.55
                + min(max(snapshot.momentum_pct, 0), 5) / 25
                + min(max(snapshot.rsi - 50, 0), 30) / 150,
            )
            signal = TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.BUY,
                confidence=round(confidence, 4),
                regime=diagnostic.regime,
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
            return signal, diagnostic

        if bearish_exit:
            signal = TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.EXIT,
                confidence=0.7,
                regime=diagnostic.regime,
                reasons=["bearish trend or momentum invalidated"],
            )
            return signal, diagnostic

        signal = TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            action=TradeAction.HOLD,
            confidence=0.5,
            regime=diagnostic.regime,
            reasons=["entry conditions not aligned"],
        )
        return signal, diagnostic

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal:
        signal, _ = self.analyze_with_diagnostic(candles, symbol, timeframe)
        return signal
