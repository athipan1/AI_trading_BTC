from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.monitoring.position_store import PositionStore


class TradePathObserver:
    """Persist prospective trade-path samples without changing trading decisions."""

    def __init__(self, position_store: PositionStore) -> None:
        self.position_store = position_store

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_symbol(value: Any) -> str:
        return str(value or "").upper()

    def capture_result(self, result: dict[str, Any]) -> dict[str, Any] | None:
        event = str(result.get("event", "")).upper()
        if event in {"BUY_FILLED", "SHORT_FILLED"}:
            position = result.get("position")
            signal = result.get("signal")
            if not isinstance(position, dict):
                return None
            signal_payload = signal if isinstance(signal, dict) else {}
            return self._capture_entry(position, signal_payload)

        if event in {"POSITION_CLOSED", "SHORT_CLOSED"}:
            position = result.get("closed_position")
            exit_order = result.get("exit_order")
            if not isinstance(position, dict) or not isinstance(exit_order, dict):
                return None
            exit_price = self._float(exit_order.get("average"))
            if exit_price is None:
                return None
            return self.observe_order_price(str(position.get("order_id", "")), exit_price)
        return None

    def _capture_entry(
        self,
        position: dict[str, Any],
        signal: dict[str, Any],
    ) -> dict[str, Any]:
        order_id = str(position.get("order_id", ""))
        if not order_id:
            raise ValueError("entry result is missing order_id")
        positions = self.position_store.load()
        target: dict[str, Any] | None = None
        for item in positions:
            if str(item.get("order_id")) != order_id:
                continue
            entry_price = self._float(item.get("entry_price"))
            stop_loss = self._float(item.get("stop_loss"))
            quantity = self._float(item.get("quantity"))
            if item.get("initial_stop_loss") is None and stop_loss is not None:
                item["initial_stop_loss"] = stop_loss
                item["initial_stop_loss_source"] = "entry_snapshot"
            if (
                item.get("initial_risk_price_distance") is None
                and entry_price is not None
                and stop_loss is not None
            ):
                risk_distance = abs(entry_price - stop_loss)
                if risk_distance > 0:
                    item["initial_risk_price_distance"] = risk_distance
                    if quantity is not None and quantity > 0:
                        item["initial_risk_usdt"] = risk_distance * quantity
                    item["initial_risk_source"] = "entry_snapshot"
            regime = signal.get("regime")
            if item.get("entry_market_regime") is None and regime:
                item["entry_market_regime"] = str(regime)
            if item.get("entry_context_captured_at") is None:
                item["entry_context_captured_at"] = self._now()
            if entry_price is not None:
                if item.get("trade_path_highest_price") is None:
                    item["trade_path_highest_price"] = entry_price
                if item.get("trade_path_lowest_price") is None:
                    item["trade_path_lowest_price"] = entry_price
            item["trade_path_observation_count"] = int(
                item.get("trade_path_observation_count") or 0
            )
            item["trade_path_basis"] = "runner_live_price_samples"
            target = item
            break
        if target is None:
            raise KeyError(f"unknown tracked order: {order_id}")
        self.position_store.save(positions)
        return target

    def observe_open_positions(self, symbol: str, price: float) -> int:
        if price <= 0:
            raise ValueError("observed price must be positive")
        normalized_symbol = self._normalize_symbol(symbol)
        positions = self.position_store.load()
        updated = 0
        now = self._now()
        for item in positions:
            if item.get("status") != "OPEN":
                continue
            if self._normalize_symbol(item.get("symbol")) != normalized_symbol:
                continue
            self._apply_price(item, price, now)
            updated += 1
        if updated:
            self.position_store.save(positions)
        return updated

    def observe_order_price(self, order_id: str, price: float) -> dict[str, Any]:
        if price <= 0:
            raise ValueError("observed price must be positive")
        positions = self.position_store.load()
        target: dict[str, Any] | None = None
        now = self._now()
        for item in positions:
            if str(item.get("order_id")) != str(order_id):
                continue
            self._apply_price(item, price, now)
            target = item
            break
        if target is None:
            raise KeyError(f"unknown tracked order: {order_id}")
        self.position_store.save(positions)
        return target

    def _apply_price(self, item: dict[str, Any], price: float, now: str) -> None:
        entry_price = self._float(item.get("entry_price"))
        highest = self._float(item.get("trade_path_highest_price"))
        lowest = self._float(item.get("trade_path_lowest_price"))
        base_high = entry_price if highest is None else highest
        base_low = entry_price if lowest is None else lowest
        item["trade_path_highest_price"] = price if base_high is None else max(base_high, price)
        item["trade_path_lowest_price"] = price if base_low is None else min(base_low, price)
        item["trade_path_observation_count"] = int(
            item.get("trade_path_observation_count") or 0
        ) + 1
        item["trade_path_last_observed_at"] = now
        item["trade_path_basis"] = "runner_live_price_samples"
