from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.execution.binance_spot_protection import BinanceSpotProtectiveExitService
from app.monitoring.position_store import PositionStore


@dataclass(frozen=True)
class ProtectiveReconciliation:
    entry_order_id: str
    state: str
    safe_to_software_exit: bool
    mutation_performed: bool
    detail: str


class BinanceSpotProtectionReconciler:
    """Fail-closed reconciliation between exchange OCO state and PositionStore."""

    def __init__(
        self,
        service: BinanceSpotProtectiveExitService,
        position_store: PositionStore,
    ) -> None:
        self.service = service
        self.position_store = position_store

    @staticmethod
    def _client_prefix(entry_order_id: str) -> str:
        return f"protect-{str(entry_order_id)[-20:]}-"

    def _all_orders(self, symbol: str) -> list[dict[str, Any]]:
        exchange_symbol, _, _ = self.service.broker._symbol_parts(symbol)
        payload = self.service.broker._request(
            "GET",
            "/api/v3/allOrders",
            params={"symbol": exchange_symbol, "limit": 1000},
            signed=True,
        )
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise RuntimeError("Binance Testnet returned invalid all-orders payload")
        return payload

    def _matching_orders(
        self,
        *,
        symbol: str,
        entry_order_id: str,
    ) -> list[dict[str, Any]]:
        prefix = self._client_prefix(entry_order_id)
        return [
            order
            for order in self._all_orders(symbol)
            if str(order.get("clientOrderId", "")).startswith(prefix)
        ]

    @staticmethod
    def _filled_order(orders: list[dict[str, Any]]) -> dict[str, Any] | None:
        filled = [
            order for order in orders if str(order.get("status", "")).upper() == "FILLED"
        ]
        if len(filled) > 1:
            raise RuntimeError("multiple protective exit orders are FILLED")
        return filled[0] if filled else None

    @staticmethod
    def _exit_reason(order: dict[str, Any]) -> str:
        order_type = str(order.get("type", "")).upper()
        client_id = str(order.get("clientOrderId", "")).lower()
        take_profit_types = {"LIMIT_MAKER", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"}
        if client_id.endswith("-tp") or order_type in take_profit_types:
            return "TP_HIT"
        if client_id.endswith("-sl") or order_type in {"STOP_LOSS", "STOP_LOSS_LIMIT"}:
            return "SL_HIT"
        return "EXCHANGE_PROTECTIVE_EXIT"

    @staticmethod
    def _fill_price(order: dict[str, Any]) -> float:
        executed = float(order.get("executedQty") or 0)
        quote = float(order.get("cummulativeQuoteQty") or 0)
        if executed > 0 and quote > 0:
            return quote / executed
        price = float(order.get("price") or order.get("stopPrice") or 0)
        if price <= 0:
            raise RuntimeError("filled protective order has no usable fill price")
        return price

    def reconcile(self, *, entry_order_id: str) -> ProtectiveReconciliation:
        matches = [
            item
            for item in self.position_store.load()
            if str(item.get("order_id")) == str(entry_order_id)
        ]
        if len(matches) != 1:
            raise RuntimeError("expected exactly one tracked position for reconciliation")
        position = matches[0]
        if str(position.get("side", "")).lower() != "buy":
            raise RuntimeError("Spot protective reconciliation supports long positions only")

        orders = self._matching_orders(
            symbol=str(position["symbol"]),
            entry_order_id=str(entry_order_id),
        )
        filled = self._filled_order(orders)
        active_statuses = {"NEW", "PARTIALLY_FILLED", "PENDING_NEW"}
        active = [
            order
            for order in orders
            if str(order.get("status", "")).upper() in active_statuses
        ]

        if filled is not None:
            if position.get("status") == "CLOSED":
                return ProtectiveReconciliation(
                    str(entry_order_id),
                    "EXCHANGE_EXIT_ALREADY_RECORDED",
                    False,
                    False,
                    "exchange protective exit is filled and local position is already closed",
                )
            local_status = str(position.get("status", "")).upper()
            if local_status not in {"OPEN", "TP_HIT", "SL_HIT"}:
                raise RuntimeError(
                    "exchange exit filled while local position is not "
                    "OPEN/TP_HIT/SL_HIT/CLOSED"
                )
            self.position_store.mark_closed(
                str(entry_order_id),
                exit_order_id=str(filled["orderId"]),
                exit_reason=self._exit_reason(filled),
                exit_price=self._fill_price(filled),
            )
            return ProtectiveReconciliation(
                str(entry_order_id),
                "EXCHANGE_EXIT_RECONCILED",
                False,
                True,
                "filled exchange protective exit was recorded locally",
            )

        if len(active) >= 2:
            if position.get("status") != "OPEN":
                raise RuntimeError("active exchange protection exists for non-open local position")
            return ProtectiveReconciliation(
                str(entry_order_id),
                "PROTECTED",
                False,
                False,
                "exchange-side OCO protection is active; software exit must not submit SELL",
            )

        if orders:
            return ProtectiveReconciliation(
                str(entry_order_id),
                "PROTECTION_INCOMPLETE",
                False,
                False,
                "protective order history exists but no complete active OCO or filled exit was found",
            )

        return ProtectiveReconciliation(
            str(entry_order_id),
            "UNPROTECTED",
            position.get("status") == "OPEN",
            False,
            "no exchange protective order history exists for this tracked position",
        )
