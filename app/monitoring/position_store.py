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
            "side": "buy",
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
        }
        positions.append(record)
        self.save(positions)
        return record

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
            target = item
            break
        if target is None:
            raise KeyError(f"unknown tracked order: {order_id}")
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
