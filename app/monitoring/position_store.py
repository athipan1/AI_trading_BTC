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
        take_profit: float,
        stop_loss: float,
    ) -> dict[str, Any]:
        positions = self.load()
        for existing in positions:
            if str(existing.get("order_id")) == str(order_id):
                return existing
        record: dict[str, Any] = {
            "order_id": str(order_id),
            "symbol": symbol.upper(),
            "side": "buy",
            "entry_price": float(entry_price),
            "quantity": float(quantity),
            "take_profit": float(take_profit),
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

    def active_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        normalized_symbol = symbol.upper() if symbol else None
        return [
            item
            for item in self.load()
            if item.get("status") == "OPEN"
            and (normalized_symbol is None or item.get("symbol") == normalized_symbol)
        ]

    def count_active(self) -> int:
        return len(self.active_positions())

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
