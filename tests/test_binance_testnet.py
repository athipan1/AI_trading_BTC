import pytest

from app.execution.binance_testnet import BinanceTestnetBroker, BinanceTestnetSafetyError


class FakeExchange:
    def __init__(self, switch_to_testnet: bool = True):
        self.switch_to_testnet = switch_to_testnet
        self.calls = []
        self.urls = {
            "api": {
                "public": "https://api.binance.com/api/v3",
                "private": "https://api.binance.com/api/v3",
            }
        }
        self.markets = {
            "BTC/USDT": {
                "symbol": "BTC/USDT",
                "spot": True,
                "active": True,
                "base": "BTC",
                "quote": "USDT",
                "limits": {"amount": {"min": 0.00001}, "cost": {"min": 1.0}},
            }
        }

    def set_sandbox_mode(self, enabled):
        self.calls.append(("set_sandbox_mode", enabled))
        if enabled and self.switch_to_testnet:
            self.urls["api"] = {
                "public": "https://testnet.binance.vision/api/v3",
                "private": "https://testnet.binance.vision/api/v3",
            }

    def load_markets(self):
        self.calls.append(("load_markets",))
        return self.markets

    def fetch_balance(self):
        self.calls.append(("fetch_balance",))
        return {"free": {"USDT": 1000.0, "BTC": 1.0}}

    def fetch_ticker(self, symbol):
        self.calls.append(("fetch_ticker", symbol))
        return {"ask": 50_010.0, "bid": 49_990.0, "last": 50_000.0}

    def amount_to_precision(self, symbol, amount):
        self.calls.append(("amount_to_precision", symbol, amount))
        return f"{amount:.6f}"

    def create_order(self, symbol, order_type, side, amount):
        self.calls.append(("create_order", symbol, order_type, side, amount))
        return {
            "id": "test-order-1",
            "clientOrderId": "client-1",
            "symbol": symbol,
            "type": order_type,
            "side": side,
            "status": "closed",
            "amount": amount,
            "filled": amount,
            "remaining": 0.0,
            "average": 50_000.0,
            "cost": amount * 50_000.0,
            "info": {"secret-ish-raw-response": "must-not-be-returned"},
        }


def factory_for(fake):
    return lambda config: fake


def test_enables_sandbox_before_any_network_call() -> None:
    fake = FakeExchange()
    broker = BinanceTestnetBroker("key", "secret", exchange_factory=factory_for(fake))
    assert fake.calls == [("set_sandbox_mode", True)]

    result = broker.preflight("BTC/USDT")
    assert result["sandbox"] is True
    assert result["credentials_valid"] is True
    assert fake.calls[1][0] == "load_markets"


def test_refuses_production_binance_urls() -> None:
    fake = FakeExchange(switch_to_testnet=False)
    with pytest.raises(BinanceTestnetSafetyError):
        BinanceTestnetBroker("key", "secret", exchange_factory=factory_for(fake))


def test_hard_notional_cap_fails_before_order_submission() -> None:
    fake = FakeExchange()
    broker = BinanceTestnetBroker(
        "key",
        "secret",
        max_order_notional_usdt=25,
        exchange_factory=factory_for(fake),
    )
    with pytest.raises(ValueError, match="hard Testnet cap"):
        broker.place_market_order("BTC/USDT", "buy", 25.01)
    assert not any(call[0] == "create_order" for call in fake.calls)


def test_market_buy_returns_sanitized_order() -> None:
    fake = FakeExchange()
    broker = BinanceTestnetBroker(
        "key",
        "secret",
        max_order_notional_usdt=25,
        exchange_factory=factory_for(fake),
    )
    result = broker.place_market_order("BTC/USDT", "buy", 10)

    assert result["order_sent"] is True
    assert result["host"] == "testnet.binance.vision"
    assert result["id"] == "test-order-1"
    assert "info" not in result
    assert any(call[0] == "create_order" for call in fake.calls)
