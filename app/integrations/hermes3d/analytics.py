from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.auto_trading.state_store import AutoTradeStateStore
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.monitoring.position_store import PositionStore


class Hermes3DTradingAnalyticsProjection:
    """Read-only trading analytics built from existing local observability stores."""

    STRATEGY_IDS = ("baseline", "triple_ema", "triple_ema_short")

    def __init__(
        self,
        *,
        journal: Hermes3DEventJournal,
        spot_position_store: PositionStore,
        futures_position_store: PositionStore,
        auto_state_paths: dict[str, str | Path],
    ) -> None:
        self.journal = journal
        self.spot_position_store = spot_position_store
        self.futures_position_store = futures_position_store
        self.auto_state_paths = {
            strategy_id: Path(path) for strategy_id, path in auto_state_paths.items()
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _positions(self) -> list[dict[str, Any]]:
        return self.spot_position_store.load() + self.futures_position_store.load()

    @staticmethod
    def _estimated_pnl(position: dict[str, Any]) -> float | None:
        if position.get("status") != "CLOSED":
            return None
        try:
            entry_price = float(position["entry_price"])
            exit_price = float(position["exit_price"])
            quantity = float(position["quantity"])
        except (KeyError, TypeError, ValueError):
            return None

        side = str(position.get("side", "buy")).lower()
        if side == "buy":
            return (exit_price - entry_price) * quantity
        if side == "sell":
            return (entry_price - exit_price) * quantity
        return None

    @classmethod
    def _trade_summary(cls, positions: list[dict[str, Any]]) -> dict[str, Any]:
        open_positions = [item for item in positions if item.get("status") == "OPEN"]
        closed_positions = [item for item in positions if item.get("status") == "CLOSED"]
        pnl_values = [pnl for item in closed_positions if (pnl := cls._estimated_pnl(item)) is not None]

        winning_trades = sum(pnl > 0 for pnl in pnl_values)
        losing_trades = sum(pnl < 0 for pnl in pnl_values)
        breakeven_trades = sum(pnl == 0 for pnl in pnl_values)
        gross_profit = sum(pnl for pnl in pnl_values if pnl > 0)
        gross_loss = sum(pnl for pnl in pnl_values if pnl < 0)
        estimated_realized_pnl = sum(pnl_values)
        evaluated_trades = winning_trades + losing_trades + breakeven_trades

        return {
            "open_positions": len(open_positions),
            "closed_trades": len(closed_positions),
            "evaluated_trades": evaluated_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "breakeven_trades": breakeven_trades,
            "win_rate_pct": round((winning_trades / evaluated_trades) * 100, 4)
            if evaluated_trades
            else 0.0,
            "gross_profit_usdt": round(gross_profit, 8),
            "gross_loss_usdt": round(gross_loss, 8),
            "estimated_realized_pnl_usdt": round(estimated_realized_pnl, 8),
            "profit_factor": round(gross_profit / abs(gross_loss), 6) if gross_loss < 0 else None,
        }

    def _strategy_metrics(self, positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        strategy_ids = set(self.STRATEGY_IDS)
        strategy_ids.update(
            str(item.get("strategy_id", "baseline")).lower()
            for item in positions
            if item.get("strategy_id")
        )
        return {
            strategy_id: self._trade_summary(
                [
                    item
                    for item in positions
                    if str(item.get("strategy_id", "baseline")).lower() == strategy_id
                ]
            )
            for strategy_id in sorted(strategy_ids)
        }

    def _risk_metrics(self) -> dict[str, Any]:
        records = self.journal.read_recent()
        risk_pass_count = sum(record.get("event") == "RISK_PASS" for record in records)
        circuit_breaker_events = sum(record.get("event") == "CIRCUIT_BREAKER" for record in records)

        halted: dict[str, dict[str, Any]] = {}
        for strategy_id, path in self.auto_state_paths.items():
            state = AutoTradeStateStore(path).load()
            if state.get("halted"):
                halted[strategy_id] = {
                    "reason": state.get("halt_reason"),
                    "halted_at": state.get("halted_at"),
                }

        return {
            "risk_pass_count": risk_pass_count,
            "circuit_breaker_active": bool(halted),
            "circuit_breaker_event_count": circuit_breaker_events,
            "halted_strategies": halted,
        }

    def analytics(self) -> dict[str, Any]:
        positions = self._positions()
        portfolio = self._trade_summary(positions)
        closed_positions = [item for item in positions if item.get("status") == "CLOSED"]

        return {
            "generated_at": self._now(),
            "read_only": True,
            "source": "position_store+hermes3d_event_journal+auto_trade_state",
            "portfolio": portfolio,
            "execution": {
                "tp_count": sum(
                    str(item.get("exit_reason", "")).upper() == "TP_HIT"
                    for item in closed_positions
                ),
                "sl_count": sum(
                    str(item.get("exit_reason", "")).upper() == "SL_HIT"
                    for item in closed_positions
                ),
            },
            "risk": self._risk_metrics(),
            "strategies": self._strategy_metrics(positions),
            "data_quality": {
                "pnl_basis": "entry_exit_estimate",
                "fees_included": False,
                "slippage_included": False,
                "exchange_fill_reconciliation": False,
                "journal_window": "bounded_recent_suffix",
            },
        }
