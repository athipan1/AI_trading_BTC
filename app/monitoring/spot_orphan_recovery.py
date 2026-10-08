from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.execution.binance_testnet import BinanceTestnetBroker
from app.monitoring.position_store import PositionStore


class SpotOrphanAuditService:
    """Read-only proof that an unresolved local Spot position lost exchange lineage."""

    ENTRY_NOT_FOUND_CODE = "code=-2013"
    UNRESOLVED_STATUSES = {"OPEN", "TP_HIT", "SL_HIT"}

    def __init__(
        self,
        *,
        broker: BinanceTestnetBroker,
        position_store: PositionStore,
    ) -> None:
        self.broker = broker
        self.position_store = position_store

    @staticmethod
    def _client_prefix(order_id: str) -> str:
        return f"protect-{str(order_id)[-20:]}-"

    @classmethod
    def _is_not_found(cls, exc: Exception) -> bool:
        return cls.ENTRY_NOT_FOUND_CODE in str(exc)

    def _entry_order_lookup(
        self,
        *,
        exchange_symbol: str,
        order_id: str,
    ) -> tuple[str, dict[str, Any] | None]:
        try:
            payload = self.broker._request(
                "GET",
                "/api/v3/order",
                params={"symbol": exchange_symbol, "orderId": int(order_id)},
                signed=True,
            )
        except RuntimeError as exc:
            if self._is_not_found(exc):
                return "NOT_FOUND", None
            raise
        if not isinstance(payload, dict):
            raise RuntimeError("Binance Spot Testnet returned invalid order lookup payload")
        return "FOUND", payload

    def _entry_fills(
        self,
        *,
        exchange_symbol: str,
        order_id: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        try:
            payload = self.broker._request(
                "GET",
                "/api/v3/myTrades",
                params={"symbol": exchange_symbol, "orderId": int(order_id)},
                signed=True,
            )
        except RuntimeError as exc:
            if self._is_not_found(exc):
                return "NOT_FOUND", []
            raise
        if not isinstance(payload, list):
            raise RuntimeError("Binance Spot Testnet returned invalid myTrades payload")
        fills = [
            item
            for item in payload
            if isinstance(item, dict) and str(item.get("orderId")) == str(order_id)
        ]
        return "FOUND" if fills else "EMPTY", fills

    def audit(self, *, order_id: str) -> dict[str, Any]:
        matches = [
            item
            for item in self.position_store.load()
            if str(item.get("order_id")) == str(order_id)
        ]
        if len(matches) != 1:
            raise RuntimeError("expected exactly one local position for orphan audit")
        position = matches[0]
        symbol = str(position.get("symbol") or "")
        if not symbol:
            raise RuntimeError("local position is missing symbol")

        exchange_symbol, _, _ = self.broker._symbol_parts(symbol)
        entry_lookup, entry_order = self._entry_order_lookup(
            exchange_symbol=exchange_symbol,
            order_id=str(order_id),
        )
        fills_lookup, entry_fills = self._entry_fills(
            exchange_symbol=exchange_symbol,
            order_id=str(order_id),
        )

        all_orders = self.broker._request(
            "GET",
            "/api/v3/allOrders",
            params={"symbol": exchange_symbol, "limit": 1000},
            signed=True,
        )
        if not isinstance(all_orders, list):
            raise RuntimeError("Binance Spot Testnet returned invalid allOrders payload")

        open_orders = self.broker._request(
            "GET",
            "/api/v3/openOrders",
            params={"symbol": exchange_symbol},
            signed=True,
        )
        if not isinstance(open_orders, list):
            raise RuntimeError("Binance Spot Testnet returned invalid openOrders payload")

        prefix = self._client_prefix(str(order_id))
        entry_history = [
            item
            for item in all_orders
            if isinstance(item, dict) and str(item.get("orderId")) == str(order_id)
        ]
        protective_history = [
            item
            for item in all_orders
            if isinstance(item, dict)
            and str(item.get("clientOrderId", "")).startswith(prefix)
        ]
        open_protective = [
            item
            for item in open_orders
            if isinstance(item, dict)
            and str(item.get("clientOrderId", "")).startswith(prefix)
        ]

        account = self.broker.account_snapshot(symbol)
        local_status = str(position.get("status", "")).upper()
        local_exit_mode = str(position.get("exit_mode", "")).lower()
        has_recorded_exit = (
            position.get("exit_order_id") is not None
            or position.get("exit_price") is not None
        )
        has_realized_pnl = (
            position.get("gross_realized_pnl") is not None
            or position.get("net_realized_pnl") is not None
        )

        checks = {
            "local_unresolved": local_status in self.UNRESOLVED_STATUSES,
            "fixed_tp_sl": local_exit_mode == "fixed_tp_sl",
            "no_recorded_exit": not has_recorded_exit,
            "no_realized_pnl": not has_realized_pnl,
            "entry_order_not_found": entry_lookup == "NOT_FOUND" and entry_order is None,
            "entry_order_absent_from_history": len(entry_history) == 0,
            "entry_fills_absent": len(entry_fills) == 0,
            "protective_history_absent": len(protective_history) == 0,
            "open_protective_orders_absent": len(open_protective) == 0,
        }
        eligible = all(checks.values())

        evidence = {
            "audited_at": datetime.now(UTC).isoformat(),
            "exchange": "binance_spot_testnet",
            "symbol": symbol,
            "entry_order_id": str(order_id),
            "entry_order_lookup": entry_lookup,
            "entry_fills_lookup": fills_lookup,
            "entry_history_count": len(entry_history),
            "entry_fill_count": len(entry_fills),
            "protective_history_count": len(protective_history),
            "open_protective_order_count": len(open_protective),
            "account_snapshot": {
                "base_total": account.get("base_total"),
                "quote_total": account.get("quote_total"),
                "reference_price": account.get("reference_price"),
                "open_orders_count": account.get("open_orders_count"),
            },
            "local_status": local_status,
            "local_exit_mode": local_exit_mode,
            "checks": checks,
        }
        return {
            "order_id": str(order_id),
            "eligible_for_quarantine": eligible,
            "checks": checks,
            "evidence": evidence,
        }

    def quarantine(
        self,
        *,
        order_id: str,
        reason: str,
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = audit or self.audit(order_id=str(order_id))
        if result.get("eligible_for_quarantine") is not True:
            raise RuntimeError("Spot position is not eligible for exchange-history-lost quarantine")
        evidence = result.get("evidence")
        if not isinstance(evidence, dict):
            raise RuntimeError("orphan audit is missing evidence")
        return self.position_store.mark_exchange_history_lost(
            str(order_id),
            reason=reason,
            evidence=evidence,
        )
