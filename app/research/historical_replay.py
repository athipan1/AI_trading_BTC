from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.models import Candle, TradeAction, TradeSignal
from app.strategies.triple_ema_breakout import TripleEMAAlignmentBreakoutStrategy
from app.strategies.triple_ema_short import TripleEMAShortStrategy


class ReplayStrategy(Protocol):
    strategy_id: str
    min_candles: int

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal: ...


@dataclass(frozen=True)
class HistoricalReplayConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    quantity: float = 0.001
    fee_rate: float = 0.001
    slippage_bps: float = 2.0


class HistoricalStrategyReplay:
    """Replay canonical strategies without touching production PositionStore or Binance."""

    SCHEMA_VERSION = "historical_replay_schema_v1"

    def __init__(self, config: HistoricalReplayConfig | None = None) -> None:
        self.config = config or HistoricalReplayConfig()

    @staticmethod
    def _iso(timestamp_ms: int) -> str:
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat()

    def _fill_price(self, price: float, side: str) -> float:
        slip = self.config.slippage_bps / 10_000
        return price * (1 + slip if side == "buy" else 1 - slip)

    def _close_trade(
        self,
        trade: dict[str, Any],
        candle: Candle,
        *,
        exit_reason: str,
    ) -> dict[str, Any]:
        side = str(trade["side"])
        exit_side = "sell" if side == "buy" else "buy"
        exit_fill = self._fill_price(candle.open, exit_side)
        entry_fill = float(trade["entry_fill_price"])
        quantity = float(trade["quantity"])
        direction = 1.0 if side == "buy" else -1.0
        gross = (exit_fill - entry_fill) * quantity * direction
        entry_fee = entry_fill * quantity * self.config.fee_rate
        exit_fee = exit_fill * quantity * self.config.fee_rate
        net = gross - entry_fee - exit_fee
        risk = float(trade["initial_risk_usdt"])
        highest = float(trade["trade_path_highest_price"])
        lowest = float(trade["trade_path_lowest_price"])
        if side == "buy":
            mfe = max(0.0, highest - entry_fill) * quantity
            mae = max(0.0, entry_fill - lowest) * quantity
        else:
            mfe = max(0.0, entry_fill - lowest) * quantity
            mae = max(0.0, highest - entry_fill) * quantity
        realized_r = net / risk if risk > 0 else None
        mfe_r = mfe / risk if risk > 0 else None
        mae_r = mae / risk if risk > 0 else None
        capture = realized_r / mfe_r if mfe_r and mfe_r > 0 else None
        profit_giveback_r = (
            mfe_r - realized_r
            if mfe_r is not None and realized_r is not None
            else None
        )
        return {
            **trade,
            "status": "CLOSED",
            "closed_at": self._iso(candle.timestamp_ms),
            "exit_reason": exit_reason,
            "exit_price": candle.open,
            "exit_fill_price": exit_fill,
            "entry_commission_usdt": entry_fee,
            "exit_commission_usdt": exit_fee,
            "total_commission_usdt": entry_fee + exit_fee,
            "gross_realized_pnl": gross,
            "net_realized_pnl": net,
            "realized_r": realized_r,
            "mae_usdt": mae,
            "mfe_usdt": mfe,
            "mae_r": mae_r,
            "mfe_r": mfe_r,
            "mfe_capture_ratio": capture,
            "profit_giveback_r": profit_giveback_r,
            "mae_utilization_r": mae_r,
            "holding_seconds": (candle.timestamp_ms - int(trade["opened_at_ms"])) / 1000,
        }

    def replay(self, candles: list[Candle], strategy: ReplayStrategy) -> dict[str, Any]:
        if len(candles) <= strategy.min_candles:
            raise ValueError(f"historical replay requires more than {strategy.min_candles} candles")
        trades: list[dict[str, Any]] = []
        active: dict[str, Any] | None = None
        for index in range(strategy.min_candles - 1, len(candles) - 1):
            history = candles[: index + 1]
            decision_candle = candles[index]
            next_candle = candles[index + 1]
            signal = strategy.analyze(history, self.config.symbol, self.config.timeframe)
            if active is not None:
                active["trade_path_highest_price"] = max(
                    float(active["trade_path_highest_price"]), decision_candle.high
                )
                active["trade_path_lowest_price"] = min(
                    float(active["trade_path_lowest_price"]), decision_candle.low
                )
                active["trade_path_observation_count"] = (
                    int(active["trade_path_observation_count"]) + 1
                )
                if signal.action == TradeAction.EXIT:
                    trades.append(
                        self._close_trade(active, next_candle, exit_reason="STRATEGY_EXIT")
                    )
                    active = None
                continue
            if signal.action == TradeAction.BUY:
                entry_side = "buy"
            elif signal.action == TradeAction.SHORT:
                entry_side = "sell"
            else:
                entry_side = None
            if entry_side is None or signal.stop_loss is None:
                continue
            entry_fill = self._fill_price(next_candle.open, entry_side)
            risk_distance = abs(entry_fill - signal.stop_loss)
            if risk_distance <= 0:
                continue
            order_id = f"hist-{strategy.strategy_id}-{next_candle.timestamp_ms}"
            active = {
                "order_id": order_id,
                "strategy_id": strategy.strategy_id,
                "symbol": self.config.symbol,
                "side": entry_side,
                "status": "OPEN",
                "created_at": self._iso(next_candle.timestamp_ms),
                "opened_at_ms": next_candle.timestamp_ms,
                "decision_at": self._iso(decision_candle.timestamp_ms),
                "entry_price": signal.entry_price or decision_candle.close,
                "entry_fill_price": entry_fill,
                "quantity": self.config.quantity,
                "initial_stop_loss": signal.stop_loss,
                "initial_risk_price_distance": risk_distance,
                "initial_risk_usdt": risk_distance * self.config.quantity,
                "entry_market_regime": signal.regime.value,
                "trade_path_highest_price": next_candle.high,
                "trade_path_lowest_price": next_candle.low,
                "trade_path_observation_count": 1,
                "historical_replay": True,
            }
        return {
            "schema_version": self.SCHEMA_VERSION,
            "basis": "canonical_strategy_replay_next_candle_execution",
            "production_position_store_mutated": False,
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe,
            "strategy_id": strategy.strategy_id,
            "source_candles": len(candles),
            "closed_trades": len(trades),
            "trades": trades,
        }

    def replay_segments(
        self,
        segments: list[list[Candle]],
        strategy: ReplayStrategy,
    ) -> dict[str, Any]:
        """Replay each continuous segment independently so state never crosses a data gap."""
        trades: list[dict[str, Any]] = []
        replayed_segments = 0
        skipped_segments = 0
        for segment in segments:
            if len(segment) <= strategy.min_candles:
                skipped_segments += 1
                continue
            result = self.replay(segment, strategy)
            replayed_segments += 1
            segment_trades = result.get("trades", [])
            if isinstance(segment_trades, list):
                trades.extend(dict(item) for item in segment_trades if isinstance(item, dict))
        return {
            "schema_version": self.SCHEMA_VERSION,
            "basis": "canonical_strategy_replay_next_candle_execution_gap_segmented",
            "production_position_store_mutated": False,
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe,
            "strategy_id": strategy.strategy_id,
            "source_candles": sum(len(segment) for segment in segments),
            "gap_policy": "segment",
            "segment_count": len(segments),
            "replayed_segment_count": replayed_segments,
            "skipped_segment_count": skipped_segments,
            "closed_trades": len(trades),
            "trades": trades,
        }


def canonical_replay_strategies() -> tuple[ReplayStrategy, ...]:
    return (TripleEMAAlignmentBreakoutStrategy(), TripleEMAShortStrategy())
