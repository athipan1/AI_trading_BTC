from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from app.execution.binance_futures_testnet import BinanceFuturesTestnetBroker
from app.execution.binance_testnet import BinanceTestnetBroker
from app.monitoring.position_store import PositionStore


@dataclass(frozen=True)
class FillSummary:
    order_id: str
    fill_count: int
    filled_quantity: float
    quote_quantity: float
    average_price: float
    commission_by_asset: dict[str, float]
    commission_quote_equivalent: float | None
    commission_quote_complete: bool
    realized_pnl: float | None
    trade_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "fill_count": self.fill_count,
            "filled_quantity": self.filled_quantity,
            "quote_quantity": self.quote_quantity,
            "average_price": self.average_price,
            "commission_by_asset": dict(self.commission_by_asset),
            "commission_quote_equivalent": self.commission_quote_equivalent,
            "commission_quote_complete": self.commission_quote_complete,
            "realized_pnl": self.realized_pnl,
            "trade_ids": list(self.trade_ids),
        }


class OrderFillSource(Protocol):
    source_name: str

    def fetch_order_fills(self, symbol: str, order_id: str) -> FillSummary:
        ...


def aggregate_binance_fills(
    fills: list[dict[str, Any]],
    *,
    order_id: str,
    base_asset: str,
    quote_asset: str,
    realized_pnl_field: str | None = None,
) -> FillSummary:
    if not fills:
        raise ValueError(f"no Binance fills found for order {order_id}")

    total_quantity = 0.0
    total_quote = 0.0
    commissions: defaultdict[str, float] = defaultdict(float)
    commission_quote = 0.0
    commission_quote_complete = True
    realized_pnl = 0.0 if realized_pnl_field else None
    trade_ids: list[str] = []

    for fill in fills:
        fill_order_id = fill.get("orderId")
        if fill_order_id is not None and str(fill_order_id) != str(order_id):
            raise ValueError("Binance fill orderId does not match requested order")

        price = float(fill.get("price", 0.0))
        quantity = float(fill.get("qty", fill.get("quantity", 0.0)))
        quote_quantity = float(fill.get("quoteQty", 0.0))
        if quote_quantity <= 0 and price > 0 and quantity > 0:
            quote_quantity = price * quantity
        if price <= 0 or quantity <= 0 or quote_quantity <= 0:
            raise ValueError("Binance fill contains non-positive price or quantity")

        total_quantity += quantity
        total_quote += quote_quantity
        commission = float(fill.get("commission", 0.0))
        commission_asset = str(fill.get("commissionAsset", "")).upper()
        if commission < 0:
            raise ValueError("Binance fill contains negative commission")
        if commission_asset:
            commissions[commission_asset] += commission
            if commission_asset == quote_asset.upper():
                commission_quote += commission
            elif commission_asset == base_asset.upper():
                commission_quote += commission * price
            elif commission > 0:
                commission_quote_complete = False
        elif commission > 0:
            commission_quote_complete = False

        if realized_pnl_field:
            assert realized_pnl is not None
            realized_pnl += float(fill.get(realized_pnl_field, 0.0))

        trade_id = fill.get("id")
        if trade_id is not None:
            trade_ids.append(str(trade_id))

    if total_quantity <= 0:
        raise ValueError(f"Binance fills for order {order_id} have zero quantity")

    return FillSummary(
        order_id=str(order_id),
        fill_count=len(fills),
        filled_quantity=total_quantity,
        quote_quantity=total_quote,
        average_price=total_quote / total_quantity,
        commission_by_asset=dict(sorted(commissions.items())),
        commission_quote_equivalent=commission_quote if commission_quote_complete else None,
        commission_quote_complete=commission_quote_complete,
        realized_pnl=realized_pnl,
        trade_ids=trade_ids,
    )


class BinanceSpotFillSource:
    source_name = "binance_spot_testnet_my_trades"

    def __init__(self, broker: BinanceTestnetBroker) -> None:
        self.broker = broker

    def fetch_order_fills(self, symbol: str, order_id: str) -> FillSummary:
        exchange_symbol, base, quote = self.broker._symbol_parts(symbol)
        payload = self.broker._request(
            "GET",
            "/api/v3/myTrades",
            params={"symbol": exchange_symbol, "orderId": int(order_id)},
            signed=True,
        )
        if not isinstance(payload, list):
            raise RuntimeError("Binance Spot Testnet returned invalid myTrades payload")
        fills = [item for item in payload if isinstance(item, dict)]
        return aggregate_binance_fills(
            fills,
            order_id=order_id,
            base_asset=base,
            quote_asset=quote,
        )


class BinanceFuturesFillSource:
    source_name = "binance_futures_demo_user_trades"

    def __init__(self, broker: BinanceFuturesTestnetBroker) -> None:
        self.broker = broker

    def fetch_order_fills(self, symbol: str, order_id: str) -> FillSummary:
        exchange_symbol, base, quote = self.broker._symbol_parts(symbol)
        payload = self.broker._request(
            "GET",
            "/fapi/v1/userTrades",
            params={"symbol": exchange_symbol, "orderId": int(order_id)},
            signed=True,
        )
        if not isinstance(payload, list):
            raise RuntimeError("Binance Futures demo returned invalid userTrades payload")
        fills = [item for item in payload if isinstance(item, dict)]
        return aggregate_binance_fills(
            fills,
            order_id=order_id,
            base_asset=base,
            quote_asset=quote,
            realized_pnl_field="realizedPnl",
        )


class PositionFillReconciler:
    """Reconcile exchange fills into the existing PositionStore without owning positions."""

    TERMINAL_CLOSED_STATUSES = {"RECONCILED", "PARTIAL"}

    def __init__(
        self,
        *,
        position_store: PositionStore,
        fill_source: OrderFillSource,
        retry_delays: tuple[float, ...] = (0.0, 1.0, 2.0),
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if not retry_delays:
            raise ValueError("retry_delays must contain at least one attempt")
        if any(delay < 0 for delay in retry_delays):
            raise ValueError("retry_delays must be non-negative")
        self.position_store = position_store
        self.fill_source = fill_source
        self.retry_delays = retry_delays
        self.sleep_fn = sleep_fn

    @classmethod
    def _is_terminal(cls, position: dict[str, Any]) -> bool:
        status = str(position.get("status", "")).upper()
        reconciliation_status = str(position.get("reconciliation_status", "")).upper()
        if status == "CLOSED":
            return reconciliation_status in cls.TERMINAL_CLOSED_STATUSES
        return reconciliation_status == "ENTRY_RECONCILED"

    def _reconcile_position(self, position: dict[str, Any]) -> dict[str, Any]:
        order_id = str(position["order_id"])
        symbol = str(position["symbol"])
        entry = self.fill_source.fetch_order_fills(symbol, order_id)
        exit_summary: FillSummary | None = None
        if position.get("status") == "CLOSED" and position.get("exit_order_id") is not None:
            exit_summary = self.fill_source.fetch_order_fills(
                symbol,
                str(position["exit_order_id"]),
            )
        return self.position_store.reconcile_fills(
            order_id,
            entry_fills=entry.to_dict(),
            exit_fills=exit_summary.to_dict() if exit_summary else None,
            source=self.fill_source.source_name,
        )

    def reconcile_all(self) -> dict[str, Any]:
        started = perf_counter()
        positions = self.position_store.load()
        reconciled = 0
        partial = 0
        pending = 0
        skipped = 0
        attempts = 0
        errors: list[dict[str, str]] = []

        for position in positions:
            order_id = position.get("order_id")
            symbol = position.get("symbol")
            if order_id is None or not symbol:
                skipped += 1
                continue
            if self._is_terminal(position):
                skipped += 1
                continue

            final_error: str | None = None
            for attempt_number, delay in enumerate(self.retry_delays, start=1):
                if delay > 0:
                    self.sleep_fn(delay)
                attempts += 1
                self.position_store.mark_reconciliation_attempt(str(order_id))
                try:
                    reconciled_position = self._reconcile_position(position)
                    reconciliation_status = str(
                        reconciled_position.get("reconciliation_status", "")
                    ).upper()
                    if reconciliation_status == "PARTIAL":
                        partial += 1
                    else:
                        reconciled += 1
                    final_error = None
                    break
                except Exception as exc:
                    final_error = f"{exc.__class__.__name__}: {exc}"
                    self.position_store.mark_reconciliation_error(str(order_id), final_error)
                    if attempt_number == len(self.retry_delays):
                        pending += 1
                        errors.append(
                            {
                                "order_id": str(order_id),
                                "error": final_error,
                            }
                        )

        return {
            "source": self.fill_source.source_name,
            "positions_seen": len(positions),
            "reconciled": reconciled,
            "partial": partial,
            "pending": pending,
            "skipped": skipped,
            "attempts": attempts,
            "error_count": len(errors),
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "errors": errors,
        }
