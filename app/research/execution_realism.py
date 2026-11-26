"""Phase 5.7.5 independent H1 research execution stress replay.

No live broker, PositionStore, frozen OOS checkpoint or promotion imports.
Each strategy sees only closed bars; an entry signal fills at the following open.
OHLC paths are unknown, so same-bar SL/TP ties use conservative stop-first.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from app.models import Candle, TradeAction, TradeSignal
from app.research.historical_replay import ReplayStrategy


@dataclass(frozen=True)
class ExecutionRealismConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    quantity: float = 0.001
    fee_rate: float = 0.001
    slippage_bps: float = 2.0
    stop_extra_slippage_bps: float = 3.0
    gap_extra_slippage_bps: float = 5.0
    venue: str = "spot"
    # Signed static funding sensitivity only; not real exchange funding history.
    funding_rate_per_8h: float = 0.0

    def __post_init__(self) -> None:
        if self.symbol != "BTC/USDT" or self.timeframe != "1h":
            raise ValueError("Phase 5.7.5 supports BTC/USDT 1h only")
        if self.venue not in {"spot", "futures"}:
            raise ValueError("venue must be spot or futures")
        values = (
            self.quantity,
            self.fee_rate,
            self.slippage_bps,
            self.stop_extra_slippage_bps,
            self.gap_extra_slippage_bps,
            self.funding_rate_per_8h,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("non-finite execution assumption")
        if not (0 < self.quantity <= 1):
            raise ValueError("quantity must be within (0, 1] BTC")
        if not (0 <= self.fee_rate <= 0.02):
            raise ValueError("fee_rate must be between 0 and 0.02")
        if not all(0 <= value <= 100 for value in (
            self.slippage_bps, self.stop_extra_slippage_bps, self.gap_extra_slippage_bps
        )):
            raise ValueError("invalid slippage assumptions")
        if abs(self.funding_rate_per_8h) > 0.01:
            raise ValueError("funding sensitivity must be within ±1% per 8h")
        if self.venue == "spot" and self.funding_rate_per_8h != 0:
            raise ValueError("spot trading has no futures funding")


class ExecutionRealismReplay:
    """Conservative deterministic replay from identical closed candles and strategy contract."""

    SCHEMA_VERSION = "execution_realism_replay_v1"
    HOUR_MS = 3_600_000
    FUNDING_MS = 8 * HOUR_MS

    def __init__(self, config: ExecutionRealismConfig | None = None) -> None:
        self.config = config or ExecutionRealismConfig()

    @staticmethod
    def _iso(timestamp_ms: int) -> str:
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat()

    @classmethod
    def _validate_bars(cls, bars: list[Candle]) -> None:
        previous: int | None = None
        for bar in bars:
            values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
            if not all(math.isfinite(v) for v in values):
                raise ValueError("non-finite OHLCV values")
            if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
                raise ValueError("OHLC range inconsistent with open/close")
            if bar.timestamp_ms % cls.HOUR_MS:
                raise ValueError("H1 open timestamp must be UTC hour aligned")
            if previous is not None and bar.timestamp_ms - previous != cls.HOUR_MS:
                raise ValueError("bar gap, duplicate or reverse timestamp: segment first")
            previous = bar.timestamp_ms

    def _fill(self, reference: float, side: str, *, extra_bps: float = 0) -> float:
        adverse = (self.config.slippage_bps + extra_bps) / 10_000
        price = reference * (1 + adverse if side == "buy" else 1 - adverse)
        if price <= 0 or not math.isfinite(price):
            raise ValueError("invalid executed price")
        return price

    @staticmethod
    def _valid_bracket(entry: float, side: str, stop: float, target: float | None) -> bool:
        if not math.isfinite(stop) or stop <= 0:
            return False
        if target is not None and (not math.isfinite(target) or target <= 0):
            return False
        if side == "buy":
            return stop < entry and (target is None or target > entry)
        return stop > entry and (target is None or target < entry)

    @staticmethod
    def _trigger(bar: Candle, active: dict[str, Any]) -> tuple[str, float, bool, bool] | None:
        """Return (reason, reference, gap, ambiguous), never assume OHLC path order."""
        side = str(active["side"])
        stop = float(active["initial_stop_loss"])
        target = active["take_profit"]
        if side == "buy":
            if bar.open <= stop:
                return "STOP_GAP", bar.open, True, False
            if target is not None and bar.open >= float(target):
                return "TAKE_PROFIT_GAP", float(target), True, False
            hit_stop = bar.low <= stop
            hit_target = target is not None and bar.high >= float(target)
        else:
            if bar.open >= stop:
                return "STOP_GAP", bar.open, True, False
            if target is not None and bar.open <= float(target):
                return "TAKE_PROFIT_GAP", float(target), True, False
            hit_stop = bar.high >= stop
            hit_target = target is not None and bar.low <= float(target)
        if hit_stop:
            return "STOP_INTRABAR", stop, False, bool(hit_target)
        if hit_target:
            return "TAKE_PROFIT_INTRABAR", float(target), False, False
        return None

    def _close(
        self,
        active: dict[str, Any],
        bar: Candle,
        *,
        reason: str,
        reference: float,
        gap: bool = False,
        ambiguous: bool = False,
    ) -> dict[str, Any]:
        direction = 1 if active["side"] == "buy" else -1
        exit_side = "sell" if direction == 1 else "buy"
        extra = self.config.stop_extra_slippage_bps if reason.startswith("STOP_") else 0.0
        if reason == "STOP_GAP":
            extra += self.config.gap_extra_slippage_bps
        exit_fill = self._fill(reference, exit_side, extra_bps=extra)
        entry = float(active["entry_fill_price"])
        quantity = self.config.quantity
        entry_fee = entry * quantity * self.config.fee_rate
        exit_fee = exit_fill * quantity * self.config.fee_rate
        gross = (exit_fill - entry) * quantity * direction
        duration_ms = bar.timestamp_ms - int(active["opened_at_ms"])
        # Static rate is a stress scenario, not observed funding events.
        # Apply at completed 8h intervals; closed at the bar-open timestamp.
        funding_intervals = duration_ms // self.FUNDING_MS
        funding = (
            funding_intervals * self.config.funding_rate_per_8h * entry * quantity * direction
            if self.config.venue == "futures" else 0.0
        )
        net = gross - entry_fee - exit_fee - funding
        risk = float(active["initial_risk_usdt"])
        return {
            **active,
            "status": "CLOSED",
            "closed_at": self._iso(bar.timestamp_ms),
            "exit_reason": reason,
            "exit_reference_price": reference,
            "exit_fill_price": exit_fill,
            "gross_realized_pnl": gross,
            "entry_commission_usdt": entry_fee,
            "exit_commission_usdt": exit_fee,
            "total_commission_usdt": entry_fee + exit_fee,
            "funding_assumption_usdt": funding,
            "funding_intervals": funding_intervals,
            "net_realized_pnl": net,
            "realized_r": net / risk,
            "initial_risk_usdt": risk,
            "holding_seconds": duration_ms / 1000,
            "stop_gap": reason == "STOP_GAP",
            "intrabar_sl_tp_ambiguous": ambiguous,
            "execution_time_precision": "H1_BAR_OPEN_BUCKET",
            "path_extrema_after_exit_unknown": True,
        }

    def _entry(
        self,
        bar: Candle,
        signal: TradeSignal,
        decision_bar: Candle,
        strategy: ReplayStrategy,
    ) -> dict[str, Any] | None:
        side = "buy" if signal.action == TradeAction.BUY else "sell"
        fill = self._fill(bar.open, side)
        stop = signal.stop_loss
        target = signal.take_profit
        if stop is None or not self._valid_bracket(fill, side, stop, target):
            return None
        risk = abs(fill - stop) * self.config.quantity
        if risk <= 0:
            return None
        return {
            "order_id": f"phase575-{strategy.strategy_id}-{bar.timestamp_ms}",
            "strategy_id": strategy.strategy_id,
            "symbol": self.config.symbol,
            "side": side,
            "status": "OPEN",
            "decision_at": self._iso(decision_bar.timestamp_ms),
            "created_at": self._iso(bar.timestamp_ms),
            "opened_at_ms": bar.timestamp_ms,
            "entry_signal_price": signal.entry_price,
            "entry_fill_price": fill,
            "initial_stop_loss": stop,
            "take_profit": target,
            "quantity": self.config.quantity,
            "initial_risk_usdt": risk,
            "entry_market_regime": signal.regime.value,
            "research_execution_only": True,
        }

    def replay(self, candles: list[Candle], strategy: ReplayStrategy) -> dict[str, Any]:
        self._validate_bars(candles)
        if len(candles) <= strategy.min_candles:
            raise ValueError(f"execution replay requires more than {strategy.min_candles} H1 bars")
        trades: list[dict[str, Any]] = []
        active: dict[str, Any] | None = None
        pending_entry: tuple[TradeSignal, Candle] | None = None
        pending_exit = False
        rejected_entries = 0
        ambiguous_count = 0
        stop_gap_count = 0
        for index, bar in enumerate(candles):
            closed_here = False
            # Orders are only acted upon at the next candle open.
            if active is not None:
                open_stop = self._trigger_open_stop(bar, active)
                if open_stop:
                    trades.append(self._close(active, bar, reason="STOP_GAP", reference=bar.open, gap=True))
                    stop_gap_count += 1
                    active = None
                    pending_exit = False
                    closed_here = True
                elif pending_exit:
                    trades.append(self._close(active, bar, reason="STRATEGY_EXIT", reference=bar.open))
                    active = None
                    pending_exit = False
                    closed_here = True
            if pending_entry is not None:
                if active is not None or closed_here:
                    raise ValueError("internal replay state: pending entry overlaps existing position")
                signal, decision_bar = pending_entry
                active = self._entry(bar, signal, decision_bar, strategy)
                if active is None:
                    rejected_entries += 1
                pending_entry = None
            if active is not None:
                trigger = self._trigger(bar, active)
                if trigger:
                    reason, reference, is_gap, ambiguous = trigger
                    trades.append(self._close(active, bar, reason=reason, reference=reference,
                                              gap=is_gap, ambiguous=ambiguous))
                    ambiguous_count += int(ambiguous)
                    stop_gap_count += int(reason == "STOP_GAP")
                    active = None
                    pending_exit = False
                    closed_here = True
            if index < strategy.min_candles - 1 or index >= len(candles) - 1:
                continue
            # The current H1 bar is fully closed at decision time; fills occur next open.
            signal = strategy.analyze(candles[:index + 1], self.config.symbol, self.config.timeframe)
            if active is not None:
                if signal.action == TradeAction.EXIT:
                    pending_exit = True
            elif not closed_here and signal.action in (TradeAction.BUY, TradeAction.SHORT):
                pending_entry = (signal, bar)
        return {
            "schema_version": self.SCHEMA_VERSION,
            "basis": "closed_H1_next_open_with_intrabar_SL_TP_stop_first",
            "config": asdict(self.config),
            "strategy_id": strategy.strategy_id,
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe,
            "source_candles": len(candles),
            "closed_trades": len(trades),
            "open_trade_excluded": active is not None,
            "rejected_unsafe_entries": rejected_entries,
            "ambiguous_sl_tp_bars": ambiguous_count,
            "stop_gap_exits": stop_gap_count,
            "intrabar_resolution_policy": "STOP_FIRST",
            "funding_basis": "STATIC_SENSITIVITY_NOT_REAL_HISTORY",
            "production_position_store_mutated": False,
            "trade_execution": False,
            "promotion_allowed": False,
            "trades": trades,
        }

    @staticmethod
    def _trigger_open_stop(bar: Candle, active: dict[str, Any]) -> bool:
        stop = float(active["initial_stop_loss"])
        return (bar.open <= stop if active["side"] == "buy" else bar.open >= stop)

    def replay_segments(
        self,
        segments: list[list[Candle]],
        strategy: ReplayStrategy,
    ) -> dict[str, Any]:
        trades: list[dict[str, Any]] = []
        skipped = 0
        reopened = 0
        ambiguous = 0
        gap_exits = 0
        rejected = 0
        for segment in segments:
            self._validate_bars(segment)
            if len(segment) <= strategy.min_candles:
                skipped += 1
                continue
            result = self.replay(segment, strategy)
            reopened += 1
            trades.extend(result["trades"])
            ambiguous += result["ambiguous_sl_tp_bars"]
            gap_exits += result["stop_gap_exits"]
            rejected += result["rejected_unsafe_entries"]
        return {
            "schema_version": self.SCHEMA_VERSION,
            "gap_policy": "segment",
            "source_candles": sum(map(len, segments)),
            "segment_count": len(segments),
            "replayed_segment_count": reopened,
            "skipped_segment_count": skipped,
            "closed_trades": len(trades),
            "ambiguous_sl_tp_bars": ambiguous,
            "stop_gap_exits": gap_exits,
            "rejected_unsafe_entries": rejected,
            "trades": trades,
            "production_position_store_mutated": False,
            "trade_execution": False,
            "promotion_allowed": False,
        }