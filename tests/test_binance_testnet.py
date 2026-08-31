from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlparse

import pytest

from app.execution.binance_testnet import BinanceTestnetBroker, BinanceTestnetSafetyError


class FakeResponse:
    def __init__(self, payload: dict | list, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeSession:
    SERVER_TIME = 1_788_187_701_419

    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, headers=None, timeout=None):
        params = dict(params or {})
        headers = dict(headers or {})
        self.calls.append((method, url, params, headers, timeout))
        path = urlparse(url).path

        if path == "/api/v3/time":
            return FakeResponse({"serverTime": self.SERVER_TIME})
        if path == "/api/v3/exchangeInfo":
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
                                {"filterType": "MIN_NOTIONAL", "minNotional": "5.00000000"},
                                {
                                    "filterType": "MARKET_LOT_SIZE",
                                    "minQty": "0.00000000",
                                    "maxQty": "100.00000000",
                                    "stepSize": "0.00000100",
                                },
                            ],
                        }
                    ]
                }
            )
        if path == "/api/v3/account":
            return FakeResponse(
                {
                    "canTrade": True,
                    "balances": [
                        {"asset": "USDT", "free": "1000.00000000", "locked": "0.00000000"},
                        {"asset": "BTC", "free": "0.10000000", "locked": "0.00000000"},
                    ],
                }
            )
        if path == "/api/v3/ticker/bookTicker":
            return FakeResponse(
                {
                    "symbol": "BTCUSDT",
                    "bidPrice": "49990.00",
                    "askPrice": "50010.00",
                }
            )
        if path == "/api/v3/ticker/price":
            return FakeResponse({"symbol": "BTCUSDT", "price": "50000.00"})
        if path == "/api/v3/openOrders":
            return FakeResponse([{"symbol": "BTCUSDT", "orderId": 999}])
        if path == "/api/v3/klines":
            interval_ms = 3_600_000
            first_open = self.SERVER_TIME - (61 * interval_ms)
            rows = []
            for index in range(62):
                open_time = first_open + index * interval_ms
                close_time = open_time + interval_ms - 1
                rows.append(
                    [
                        open_time,
                        "50000.00",
                        "50100.00",
                        "49900.00",
                        "50010.00",
                        "12.0",
                        close_time,
                    ]
                )
            return FakeResponse(rows)
        if path == "/api/v3/order":
            if params.get("side") == "SELL":
                quantity = Decimal(str(params["quantity"]))
                quote_qty = quantity * Decimal("49990")
                return FakeResponse(
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 222222222,
                        "clientOrderId": "exit-1",
                        "transactTime": self.SERVER_TIME,
                        "executedQty": format(quantity, "f"),
                        "cummulativeQuoteQty": format(quote_qty, "f"),
                        "status": "FILLED",
                        "type": "MARKET",
                        "side": "SELL",
                        "fills": [],
                    }
                )
            return FakeResponse(
                {
                    "symbol": "BTCUSDT",
                    "orderId": 123456789,
                    "clientOrderId": "client-1",
                    "transactTime": self.SERVER_TIME,
                    "price": "0.00000000",
                    "origQty": "0.00019996",
                    "executedQty": "0.00019996",
                    "cummulativeQuoteQty": "10.00000000",
                    "status": "FILLED",
                    "type": "MARKET",
                    "side": "BUY",
                    "fills": [{"price": "50010.00", "qty": "0.00019996"}],
                }
            )
        raise AssertionError(f"unexpected request path: {path}")


def test_refuses_production_binance_url() -> None:
    with pytest.raises(BinanceTestnetSafetyError):
        BinanceTestnetBroker(
            "key",
            "secret",
            base_url="https://api.binance.com",
            session=FakeSession(),
        )


def test_preflight_uses_signed_testnet_account_request() -> None:
    fake = FakeSession()
    broker = BinanceTestnetBroker("key", "secret", session=fake)

    result = broker.preflight("BTC/USDT")

    assert result["sandbox"] is True
    assert result["credentials_valid"] is True
    assert result["host"] == "testnet.binance.vision"
    account_call = next(call for call in fake.calls if urlparse(call[1]).path == "/api/v3/account")
    assert account_call[3]["X-MBX-APIKEY"] == "key"
    assert "signature" in account_call[2]
    assert account_call[2]["timestamp"] == FakeSession.SERVER_TIME


def test_hard_notional_cap_fails_before_order_submission() -> None:
    fake = FakeSession()
    broker = BinanceTestnetBroker(
        "key",
        "secret",
        max_order_notional_usdt=25,
        session=fake,
    )

    with pytest.raises(ValueError, match="hard Testnet cap"):
        broker.place_market_order("BTC/USDT", "buy", 25.01)

    assert not any(urlparse(call[1]).path == "/api/v3/order" for call in fake.calls)


def test_market_buy_uses_quote_order_qty_and_returns_sanitized_order_id() -> None:
    fake = FakeSession()
    broker = BinanceTestnetBroker(
        "key",
        "secret",
        max_order_notional_usdt=25,
        session=fake,
    )

    result = broker.place_market_order("BTC/USDT", "buy", 10)

    assert result["order_sent"] is True
    assert result["host"] == "testnet.binance.vision"
    assert result["id"] == "123456789"
    assert result["order_id"] == 123456789
    assert result["status"] == "FILLED"
    assert result["cost"] == 10.0

    order_call = next(call for call in fake.calls if urlparse(call[1]).path == "/api/v3/order")
    assert order_call[0] == "POST"
    assert order_call[2]["symbol"] == "BTCUSDT"
    assert order_call[2]["side"] == "BUY"
    assert order_call[2]["type"] == "MARKET"
    assert order_call[2]["quoteOrderQty"] == "10"
    assert "signature" in order_call[2]
    assert order_call[3]["X-MBX-APIKEY"] == "key"


def test_market_buy_rejects_below_exchange_min_notional() -> None:
    fake = FakeSession()
    broker = BinanceTestnetBroker("key", "secret", session=fake)

    with pytest.raises(ValueError, match="below exchange minimum"):
        broker.place_market_order("BTC/USDT", "buy", 4.99)

    assert not any(urlparse(call[1]).path == "/api/v3/order" for call in fake.calls)


def test_account_snapshot_reports_balance_value_and_open_orders() -> None:
    fake = FakeSession()
    broker = BinanceTestnetBroker("key", "secret", session=fake)

    snapshot = broker.account_snapshot("BTC/USDT")

    assert snapshot["quote_total"] == 1000.0
    assert snapshot["base_total"] == 0.1
    assert snapshot["reference_price"] == 50_000.0
    assert snapshot["estimated_portfolio_value_quote"] == 6000.0
    assert snapshot["open_orders_count"] == 1


def test_fetch_closed_candles_excludes_current_open_candle() -> None:
    fake = FakeSession()
    broker = BinanceTestnetBroker("key", "secret", session=fake)

    candles = broker.fetch_closed_candles("BTC/USDT", interval="1h", limit=60)

    assert len(candles) == 60
    assert candles[-1].timestamp_ms < FakeSession.SERVER_TIME
    assert candles[-1].close == 50_010.0


def test_exact_quantity_sell_closes_only_requested_tracked_lot() -> None:
    fake = FakeSession()
    broker = BinanceTestnetBroker("key", "secret", session=fake)

    result = broker.place_market_sell_quantity("BTC/USDT", 0.0002)

    assert result["order_id"] == 222222222
    assert result["side"] == "sell"
    order_call = [
        call
        for call in fake.calls
        if urlparse(call[1]).path == "/api/v3/order" and call[2].get("side") == "SELL"
    ][0]
    assert Decimal(str(order_call[2]["quantity"])) == Decimal("0.0002")
