from __future__ import annotations

from urllib.parse import urlparse

import pytest

from app.execution.binance_spot_protection import BinanceSpotProtectiveExitService
from app.execution.binance_testnet import BinanceTestnetBroker, BinanceTestnetSafetyError
from tests.test_binance_testnet import FakeResponse, FakeSession


class ProtectionSession(FakeSession):
    def __init__(self, *, existing: bool = False, current_price: str = "77500.00") -> None:
        super().__init__()
        self.existing = existing
        self.current_price = current_price

    def request(self, method, url, params=None, headers=None, timeout=None):
        params = dict(params or {})
        path = urlparse(url).path
        if path == "/api/v3/exchangeInfo":
            self.calls.append((method, url, params, dict(headers or {}), timeout))
            return FakeResponse(
                {
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "status": "TRADING",
                            "baseAsset": "BTC",
                            "quoteAsset": "USDT",
                            "isSpotTradingAllowed": True,
                            "quoteOrderQtyMarketAllowed": True,
                            "filters": [
                                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                                {
                                    "filterType": "LOT_SIZE",
                                    "minQty": "0.00001",
                                    "maxQty": "100",
                                    "stepSize": "0.00001",
                                },
                            ],
                        }
                    ]
                }
            )
        if path == "/api/v3/ticker/price":
            self.calls.append((method, url, params, dict(headers or {}), timeout))
            return FakeResponse({"symbol": "BTCUSDT", "price": self.current_price})
        if path == "/api/v3/openOrders":
            self.calls.append((method, url, params, dict(headers or {}), timeout))
            if not self.existing:
                return FakeResponse([])
            return FakeResponse(
                [
                    {
                        "orderId": 11,
                        "orderListId": 99,
                        "side": "SELL",
                        "type": "LIMIT_MAKER",
                        "price": "78483.55",
                        "stopPrice": "0",
                        "origQty": "0.00012",
                        "clientOrderId": "protect-3489476-tp",
                    },
                    {
                        "orderId": 12,
                        "orderListId": 99,
                        "side": "SELL",
                        "type": "STOP_LOSS",
                        "price": "0",
                        "stopPrice": "77059.52",
                        "origQty": "0.00012",
                        "clientOrderId": "protect-3489476-sl",
                    },
                ]
            )
        if path == "/api/v3/orderList/oco":
            self.calls.append((method, url, params, dict(headers or {}), timeout))
            return FakeResponse(
                {
                    "orderListId": 99,
                    "listStatusType": "EXEC_STARTED",
                    "listOrderStatus": "EXECUTING",
                }
            )
        return super().request(method, url, params=params, headers=headers, timeout=timeout)


def _service(session: ProtectionSession) -> BinanceSpotProtectiveExitService:
    return BinanceSpotProtectiveExitService(
        BinanceTestnetBroker("key", "secret", session=session)
    )


def test_audit_detects_exchange_side_protection() -> None:
    result = _service(ProtectionSession(existing=True)).audit(
        symbol="BTC/USDT", entry_order_id="3489476"
    )
    assert result["protected"] is True
    assert result["matching_open_orders"] == 2


def test_place_oco_uses_sell_and_exchange_quantization() -> None:
    session = ProtectionSession()
    result = _service(session).place_oco(
        symbol="BTC/USDT",
        entry_order_id="3489476",
        quantity=0.000129,
        take_profit=78483.559,
        stop_loss=77059.529,
    )
    assert result.order_list_id == 99
    call = next(item for item in session.calls if urlparse(item[1]).path == "/api/v3/orderList/oco")
    assert call[0] == "POST"
    assert call[2]["side"] == "SELL"
    assert call[2]["quantity"] == "0.00012"
    assert call[2]["abovePrice"] == "78483.55"
    assert call[2]["belowStopPrice"] == "77059.52"


def test_place_oco_refuses_duplicate_protection() -> None:
    with pytest.raises(BinanceTestnetSafetyError, match="duplicate protection"):
        _service(ProtectionSession(existing=True)).place_oco(
            symbol="BTC/USDT",
            entry_order_id="3489476",
            quantity=0.00012,
            take_profit=78483.55,
            stop_loss=77059.52,
        )


def test_place_oco_refuses_invalid_live_price_relationship() -> None:
    with pytest.raises(BinanceTestnetSafetyError, match="stop-loss < current price < take-profit"):
        _service(ProtectionSession(current_price="79000")).place_oco(
            symbol="BTC/USDT",
            entry_order_id="3489476",
            quantity=0.00012,
            take_profit=78483.55,
            stop_loss=77059.52,
        )
