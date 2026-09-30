from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.monitoring.position_store import PositionStore


class Hermes3DTradeHistoryProjection:
    """Read-only projection of production spot and futures trade history."""

    def __init__(
        self,
        *,
        spot_position_store: PositionStore,
        futures_position_store: PositionStore,
        limit: int = 100,
    ) -> None:
        self.spot_position_store = spot_position_store
        self.futures_position_store = futures_position_store
        self.limit = max(1, limit)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _realized_pnl(position: dict[str, Any]) -> tuple[float | None, str]:
        if position.get("status") != "CLOSED":
            return None, "unavailable"
        reconciled = position.get("net_realized_pnl")
        if reconciled is not None:
            try:
                return float(reconciled), "exchange_reconciled"
            except (TypeError, ValueError):
                pass
        try:
            entry = float(position["entry_price"])
            exit_price = float(position["exit_price"])
            quantity = float(position["quantity"])
        except (KeyError, TypeError, ValueError):
            return None, "unavailable"
        side = str(position.get("side", "")).lower()
        if side == "buy":
            return (exit_price - entry) * quantity, "entry_exit_estimate"
        if side == "sell":
            return (entry - exit_price) * quantity, "entry_exit_estimate"
        return None, "unavailable"

    @classmethod
    def _trade(cls, position: dict[str, Any], venue: str) -> dict[str, Any]:
        pnl, pnl_basis = cls._realized_pnl(position)
        return {
            "order_id": str(position.get("order_id", "")),
            "exit_order_id": position.get("exit_order_id"),
            "symbol": position.get("symbol"),
            "side": "LONG" if str(position.get("side", "")).lower() == "buy" else "SHORT",
            "strategy_id": position.get("strategy_id"),
            "venue": venue,
            "status": position.get("status"),
            "entry_price": position.get("entry_fill_price") or position.get("entry_price"),
            "exit_price": position.get("exit_fill_price") or position.get("exit_price"),
            "quantity": position.get("entry_filled_quantity") or position.get("quantity"),
            "take_profit": position.get("take_profit"),
            "stop_loss": position.get("stop_loss"),
            "exit_reason": position.get("exit_reason"),
            "opened_at": position.get("created_at"),
            "closed_at": position.get("closed_at"),
            "realized_pnl_usdt": pnl,
            "pnl_basis": pnl_basis,
            "reconciliation_status": position.get("reconciliation_status"),
            "entry_commission_usdt": position.get("entry_commission_quote_equivalent"),
            "exit_commission_usdt": position.get("exit_commission_quote_equivalent"),
            "entry_slippage_bps": position.get("entry_slippage_bps"),
            "exit_slippage_bps": position.get("exit_slippage_bps"),
        }

    def history(self) -> dict[str, Any]:
        positions = [
            *((item, "SPOT") for item in self.spot_position_store.load()),
            *((item, "FUTURES") for item in self.futures_position_store.load()),
        ]
        closed = [
            self._trade(position, venue)
            for position, venue in positions
            if position.get("status") == "CLOSED"
        ]
        closed.sort(key=lambda item: str(item.get("closed_at") or ""), reverse=True)
        evaluated = [float(item["realized_pnl_usdt"]) for item in closed if item["realized_pnl_usdt"] is not None]
        wins = sum(value > 0 for value in evaluated)
        losses = sum(value < 0 for value in evaluated)
        breakeven = sum(value == 0 for value in evaluated)
        return {
            "generated_at": self._now(),
            "read_only": True,
            "source": "production_position_stores",
            "summary": {
                "closed_trades": len(closed),
                "evaluated_trades": len(evaluated),
                "winning_trades": wins,
                "losing_trades": losses,
                "breakeven_trades": breakeven,
                "win_rate_pct": round((wins / len(evaluated)) * 100, 4) if evaluated else 0.0,
                "realized_pnl_usdt": round(sum(evaluated), 8),
            },
            "trades": closed[: self.limit],
            "returned_trades": min(len(closed), self.limit),
            "total_trades": len(closed),
        }
