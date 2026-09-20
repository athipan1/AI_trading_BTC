from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from app.execution.binance_testnet import BinanceTestnetBroker, BinanceTestnetSafetyError


@dataclass(frozen=True)
class ProtectiveExit:
    order_list_id: int
    symbol: str
    quantity: float
    take_profit: float
    stop_loss: float
    status: str


class BinanceSpotProtectiveExitService:
    """Exchange-side OCO protection for tracked Binance Spot Testnet long positions."""

    def __init__(self, broker: BinanceTestnetBroker) -> None:
        self.broker = broker

    @staticmethod
    def _filter(market: dict[str, Any], filter_type: str) -> dict[str, Any]:
        for item in market.get("filters") or []:
            if isinstance(item, dict) and item.get("filterType") == filter_type:
                return item
        raise RuntimeError(f"Binance Testnet market metadata is missing {filter_type}")

    @staticmethod
    def _floor(value: Decimal, step: Decimal) -> Decimal:
        if step <= 0:
            raise ValueError("exchange step must be positive")
        return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

    def _normalized_levels(
        self,
        *,
        symbol: str,
        quantity: float,
        take_profit: float,
        stop_loss: float,
    ) -> tuple[str, Decimal, Decimal, Decimal]:
        if quantity <= 0 or take_profit <= 0 or stop_loss <= 0:
            raise ValueError("protective exit quantity and prices must be positive")
        if stop_loss >= take_profit:
            raise ValueError("long protective stop-loss must be below take-profit")

        market = self.broker._load_market(symbol)
        exchange_symbol, _, quote = self.broker._symbol_parts(symbol)
        if quote != "USDT":
            raise ValueError("protective exit only allows USDT-quoted spot symbols")

        lot = self._filter(market, "LOT_SIZE")
        price_filter = self._filter(market, "PRICE_FILTER")
        step = Decimal(str(lot.get("stepSize", "0")))
        tick = Decimal(str(price_filter.get("tickSize", "0")))
        normalized_qty = self._floor(Decimal(str(quantity)), step)
        normalized_tp = self._floor(Decimal(str(take_profit)), tick)
        normalized_sl = self._floor(Decimal(str(stop_loss)), tick)
        if normalized_qty <= 0 or normalized_tp <= 0 or normalized_sl <= 0:
            raise ValueError("protective exit rounds to an unusable exchange value")
        return exchange_symbol, normalized_qty, normalized_tp, normalized_sl

    def open_orders(self, symbol: str) -> list[dict[str, Any]]:
        exchange_symbol, _, _ = self.broker._symbol_parts(symbol)
        payload = self.broker._request(
            "GET",
            "/api/v3/openOrders",
            params={"symbol": exchange_symbol},
            signed=True,
        )
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise RuntimeError("Binance Testnet returned invalid open-orders payload")
        return payload

    def audit(self, *, symbol: str, entry_order_id: str) -> dict[str, Any]:
        orders = self.open_orders(symbol)
        matching = [
            item
            for item in orders
            if str(item.get("clientOrderId", "")).startswith(f"protect-{entry_order_id}-")
        ]
        return {
            "symbol": symbol.upper(),
            "entry_order_id": str(entry_order_id),
            "protected": len(matching) >= 2,
            "matching_open_orders": len(matching),
            "orders": [
                {
                    "order_id": item.get("orderId"),
                    "order_list_id": item.get("orderListId"),
                    "side": item.get("side"),
                    "type": item.get("type"),
                    "price": item.get("price"),
                    "stop_price": item.get("stopPrice"),
                    "quantity": item.get("origQty"),
                    "client_order_id": item.get("clientOrderId"),
                }
                for item in matching
            ],
        }

    def place_oco(
        self,
        *,
        symbol: str,
        entry_order_id: str,
        quantity: float,
        take_profit: float,
        stop_loss: float,
    ) -> ProtectiveExit:
        existing = self.audit(symbol=symbol, entry_order_id=entry_order_id)
        if existing["matching_open_orders"]:
            raise BinanceTestnetSafetyError(
                f"refusing duplicate protection for entry order {entry_order_id}"
            )

        exchange_symbol, qty, tp, sl = self._normalized_levels(
            symbol=symbol,
            quantity=quantity,
            take_profit=take_profit,
            stop_loss=stop_loss,
        )
        current = Decimal(str(self.broker.current_price(symbol)))
        if not sl < current < tp:
            raise BinanceTestnetSafetyError(
                "refusing OCO placement unless stop-loss < current price < take-profit"
            )

        suffix = str(entry_order_id)[-20:]
        payload = self.broker._request(
            "POST",
            "/api/v3/orderList/oco",
            params={
                "symbol": exchange_symbol,
                "side": "SELL",
                "quantity": self.broker._format_decimal(qty),
                "aboveType": "LIMIT_MAKER",
                "abovePrice": self.broker._format_decimal(tp),
                "aboveClientOrderId": f"protect-{suffix}-tp",
                "belowType": "STOP_LOSS",
                "belowStopPrice": self.broker._format_decimal(sl),
                "belowClientOrderId": f"protect-{suffix}-sl",
                "listClientOrderId": f"protect-{suffix}",
                "newOrderRespType": "RESULT",
            },
            signed=True,
        )
        if not isinstance(payload, dict) or payload.get("orderListId") is None:
            raise RuntimeError("Binance Testnet returned invalid OCO acknowledgement")
        return ProtectiveExit(
            order_list_id=int(payload["orderListId"]),
            symbol=symbol.upper(),
            quantity=float(qty),
            take_profit=float(tp),
            stop_loss=float(sl),
            status=str(payload.get("listStatusType") or payload.get("listOrderStatus") or "UNKNOWN"),
        )
