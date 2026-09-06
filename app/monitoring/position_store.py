from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PositionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("position store must contain a JSON list")
        return [item for item in payload if isinstance(item, dict)]

    def save(self, positions: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(positions, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, self.path)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _add_position(
        self,
        *,
        order_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        take_profit: float | None,
        stop_loss: float,
        strategy_id: str,
        exit_mode: str,
    ) -> dict[str, Any]:
        if side not in {"buy", "sell"}:
            raise ValueError("position side must be buy or sell")
        positions = self.load()
        normalized_symbol = symbol.upper()
        normalized_strategy = strategy_id.lower()
        for existing in positions:
            if str(existing.get("order_id")) == str(order_id):
                return existing
            if (
                existing.get("status") == "OPEN"
                and existing.get("symbol") == normalized_symbol
                and str(existing.get("strategy_id", "baseline")).lower() == normalized_strategy
            ):
                raise ValueError(
                    f"strategy {normalized_strategy} already has an OPEN position for {normalized_symbol}"
                )
        record: dict[str, Any] = {
            "order_id": str(order_id),
            "strategy_id": normalized_strategy,
            "exit_mode": exit_mode,
            "symbol": normalized_symbol,
            "side": side,
            "entry_price": float(entry_price),
            "quantity": float(quantity),
            "take_profit": float(take_profit) if take_profit is not None else None,
            "stop_loss": float(stop_loss),
            "status": "OPEN",
            "notification_sent": False,
            "created_at": self._now(),
            "triggered_at": None,
            "hit_price": None,
            "exit_order_id": None,
            "exit_reason": None,
            "exit_price": None,
            "closed_at": None,
            "reconciliation_status": "PENDING",
            "reconciliation_source": None,
            "reconciled_at": None,
            "entry_fill_price": None,
            "entry_filled_quantity": None,
            "entry_fill_count": None,
            "entry_commission_by_asset": None,
            "entry_commission_quote_equivalent": None,
            "entry_slippage_bps": None,
            "exit_fill_price": None,
            "exit_filled_quantity": None,
            "exit_fill_count": None,
            "exit_commission_by_asset": None,
            "exit_commission_quote_equivalent": None,
            "exit_slippage_bps": None,
            "gross_realized_pnl": None,
            "net_realized_pnl": None,
            "realized_pnl_basis": None,
        }
        positions.append(record)
        self.save(positions)
        return record

    def add_long_position(
        self,
        *,
        order_id: str,
        symbol: str,
        entry_price: float,
        quantity: float,
        take_profit: float | None,
        stop_loss: float,
        strategy_id: str = "baseline",
        exit_mode: str = "fixed_tp_sl",
    ) -> dict[str, Any]:
        return self._add_position(
            order_id=order_id,
            symbol=symbol,
            side="buy",
            entry_price=entry_price,
            quantity=quantity,
            take_profit=take_profit,
            stop_loss=stop_loss,
            strategy_id=strategy_id,
            exit_mode=exit_mode,
        )

    def add_short_position(
        self,
        *,
        order_id: str,
        symbol: str,
        entry_price: float,
        quantity: float,
        take_profit: float | None,
        stop_loss: float,
        strategy_id: str = "triple_ema_short",
        exit_mode: str = "close_above_ema50",
    ) -> dict[str, Any]:
        return self._add_position(
            order_id=order_id,
            symbol=symbol,
            side="sell",
            entry_price=entry_price,
            quantity=quantity,
            take_profit=take_profit,
            stop_loss=stop_loss,
            strategy_id=strategy_id,
            exit_mode=exit_mode,
        )

    def active_positions(
        self,
        symbol: str | None = None,
        strategy_id: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_symbol = symbol.upper() if symbol else None
        normalized_strategy = strategy_id.lower() if strategy_id else None
        return [
            item
            for item in self.load()
            if item.get("status") == "OPEN"
            and (normalized_symbol is None or item.get("symbol") == normalized_symbol)
            and (
                normalized_strategy is None
                or str(item.get("strategy_id", "baseline")).lower() == normalized_strategy
            )
        ]

    def count_active(self, strategy_id: str | None = None) -> int:
        return len(self.active_positions(strategy_id=strategy_id))

    def update_stop_loss(self, order_id: str, stop_loss: float) -> dict[str, Any]:
        if stop_loss <= 0:
            raise ValueError("stop_loss must be positive")
        positions = self.load()
        target: dict[str, Any] | None = None
        for item in positions:
            if str(item.get("order_id")) != str(order_id):
                continue
            if item.get("status") != "OPEN":
                raise ValueError("cannot update stop_loss for a non-open position")
            item["stop_loss"] = float(stop_loss)
            item["stop_updated_at"] = self._now()
            target = item
            break
        if target is None:
            raise KeyError(f"unknown tracked order: {order_id}")
        self.save(positions)
        return target

    def mark_triggered(self, order_id: str, event: str, hit_price: float) -> dict[str, Any]:
        positions = self.load()
        target: dict[str, Any] | None = None
        for item in positions:
            if str(item.get("order_id")) != str(order_id):
                continue
            item["status"] = event.upper()
            item["hit_price"] = float(hit_price)
            item["triggered_at"] = self._now()
            item["notification_sent"] = False
            target = item
            break
        if target is None:
            raise KeyError(f"unknown tracked order: {order_id}")
        self.save(positions)
        return target

    def mark_closed(
        self,
        order_id: str,
        *,
        exit_order_id: str,
        exit_reason: str,
        exit_price: float,
    ) -> dict[str, Any]:
        positions = self.load()
        target: dict[str, Any] | None = None
        for item in positions:
            if str(item.get("order_id")) != str(order_id):
                continue
            item["status"] = "CLOSED"
            item["exit_order_id"] = str(exit_order_id)
            item["exit_reason"] = exit_reason.upper()
            item["exit_price"] = float(exit_price)
            item["closed_at"] = self._now()
            item["notification_sent"] = True
            if item.get("reconciliation_status") != "RECONCILED":
                item["reconciliation_status"] = "PENDING"
            target = item
            break
        if target is None:
            raise KeyError(f"unknown tracked order: {order_id}")
        self.save(positions)
        return target

    @staticmethod
    def _slippage_bps(*, side: str, reference_price: float, actual_price: float) -> float | None:
        if reference_price <= 0 or actual_price <= 0:
            return None
        if side == "buy":
            return ((actual_price - reference_price) / reference_price) * 10_000
        if side == "sell":
            return ((reference_price - actual_price) / reference_price) * 10_000
        return None

    def reconcile_fills(
        self,
        order_id: str,
        *,
        entry_fills: dict[str, Any],
        exit_fills: dict[str, Any] | None,
        source: str,
    ) -> dict[str, Any]:
        if str(entry_fills.get("order_id")) != str(order_id):
            raise ValueError("entry fill summary does not match tracked order")

        positions = self.load()
        target: dict[str, Any] | None = None
        for item in positions:
            if str(item.get("order_id")) != str(order_id):
                continue
            target = item
            break
        if target is None:
            raise KeyError(f"unknown tracked order: {order_id}")

        entry_fill_price = float(entry_fills["average_price"])
        entry_qty = float(entry_fills["filled_quantity"])
        target["entry_fill_price"] = entry_fill_price
        target["entry_filled_quantity"] = entry_qty
        target["entry_fill_count"] = int(entry_fills["fill_count"])
        target["entry_commission_by_asset"] = dict(entry_fills.get("commission_by_asset") or {})
        target["entry_commission_quote_equivalent"] = entry_fills.get(
            "commission_quote_equivalent"
        )
        target["entry_slippage_bps"] = self._slippage_bps(
            side=str(target.get("side", "buy")).lower(),
            reference_price=float(target["entry_price"]),
            actual_price=entry_fill_price,
        )
        target["reconciliation_source"] = source
        target["reconciled_at"] = self._now()

        if target.get("status") != "CLOSED":
            target["reconciliation_status"] = "ENTRY_RECONCILED"
            self.save(positions)
            return target

        if exit_fills is None:
            target["reconciliation_status"] = "PENDING"
            self.save(positions)
            return target
        if str(exit_fills.get("order_id")) != str(target.get("exit_order_id")):
            raise ValueError("exit fill summary does not match tracked exit order")

        exit_fill_price = float(exit_fills["average_price"])
        exit_qty = float(exit_fills["filled_quantity"])
        target["exit_fill_price"] = exit_fill_price
        target["exit_filled_quantity"] = exit_qty
        target["exit_fill_count"] = int(exit_fills["fill_count"])
        target["exit_commission_by_asset"] = dict(exit_fills.get("commission_by_asset") or {})
        target["exit_commission_quote_equivalent"] = exit_fills.get(
            "commission_quote_equivalent"
        )
        exit_side = "sell" if str(target.get("side", "buy")).lower() == "buy" else "buy"
        target["exit_slippage_bps"] = self._slippage_bps(
            side=exit_side,
            reference_price=float(target["exit_price"]),
            actual_price=exit_fill_price,
        )

        exchange_realized = exit_fills.get("realized_pnl")
        if exchange_realized is not None:
            gross_pnl = float(exchange_realized)
            pnl_basis = "binance_realized_pnl"
        else:
            pnl_qty = min(float(target.get("quantity", entry_qty)), entry_qty, exit_qty)
            if str(target.get("side", "buy")).lower() == "buy":
                gross_pnl = (exit_fill_price - entry_fill_price) * pnl_qty
            else:
                gross_pnl = (entry_fill_price - exit_fill_price) * pnl_qty
            pnl_basis = "exchange_fill_price_difference"

        entry_fee = entry_fills.get("commission_quote_equivalent")
        exit_fee = exit_fills.get("commission_quote_equivalent")
        target["gross_realized_pnl"] = gross_pnl
        target["realized_pnl_basis"] = pnl_basis
        if entry_fee is not None and exit_fee is not None:
            target["net_realized_pnl"] = gross_pnl - float(entry_fee) - float(exit_fee)
            target["reconciliation_status"] = "RECONCILED"
        else:
            target["net_realized_pnl"] = None
            target["reconciliation_status"] = "PARTIAL"

        target["reconciled_at"] = self._now()
        self.save(positions)
        return target

    def mark_notification_sent(self, order_id: str) -> None:
        positions = self.load()
        found = False
        for item in positions:
            if str(item.get("order_id")) == str(order_id):
                item["notification_sent"] = True
                found = True
                break
        if not found:
            raise KeyError(f"unknown tracked order: {order_id}")
        self.save(positions)

    def pending_notifications(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self.load()
            if item.get("status") in {"TP_HIT", "SL_HIT"} and not item.get("notification_sent")
        ]
