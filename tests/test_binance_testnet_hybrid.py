from __future__ import annotations

import pytest

from app.execution.binance_testnet_hybrid import (
    BinancePublicMarketData,
    BinancePublicMarketDataSafetyError,
    BinanceSpotTestnetHybridBroker,
)
from app.models import Candle


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *, server_time: int, klines: list[list[object]]):
        self.server_time = server_time
        self.klines = klines
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method, url, params=None, timeout=None):
        request_params = dict(params or {})
        self.requests.append((method, url, request_params))
        if url.endswith("/api/v3/time"):
            return FakeResponse({"serverTime": self.server_time})
        if url.endswith("/api/v3/klines"):
            return FakeResponse(self.klines)
        raise AssertionError(f"unexpected URL: {url}")


class FakePublicMarketData:
    def __init__(self):
        self.calls: list[tuple[str, str, int]] = []

    def fetch_closed_candles(self, symbol: str, interval: str, limit: int):
        self.calls.append((symbol, interval, limit))
        return [
            Candle(
                timestamp_ms=index * 3_600_000,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=1.0,
            )
            for index in range(limit)
        ]


def _kline(index: int) -> list[object]:
    hour_ms = 3_600_000
    open_time = index * hour_ms
    close_time = (index + 1) * hour_ms - 1
    return [
        open_time,
        "100.0",
        "101.0",
        "99.0",
        "100.5",
        "12.0",
        close_time,
    ]


def test_public_market_data_returns_full_closed_history_for_triple_ema():
    hour_ms = 3_600_000
    session = FakeSession(
        server_time=205 * hour_ms,
        klines=[_kline(index) for index in range(3, 204)],
    )
    market_data = BinancePublicMarketData(session=session)

    candles = market_data.fetch_closed_candles("BTC/USDT", interval="1h", limit=201)

    assert len(candles) == 201
    assert candles[0].timestamp_ms == 3 * hour_ms
    assert candles[-1].timestamp_ms == 203 * hour_ms
    assert session.requests[-1][2]["symbol"] == "BTCUSDT"
    assert session.requests[-1][2]["limit"] == 203


def test_public_market_data_fails_closed_when_history_is_short():
    hour_ms = 3_600_000
    session = FakeSession(
        server_time=73 * hour_ms,
        klines=[_kline(index) for index in range(72)],
    )
    market_data = BinancePublicMarketData(session=session)

    with pytest.raises(RuntimeError, match="only 72 of 201 required closed candles"):
        market_data.fetch_closed_candles("BTC/USDT", interval="1h", limit=201)


def test_public_market_data_rejects_unexpected_host():
    with pytest.raises(BinancePublicMarketDataSafetyError):
        BinancePublicMarketData(base_url="https://testnet.binance.vision")


def test_hybrid_broker_delegates_candles_to_public_market_data():
    public_market_data = FakePublicMarketData()
    broker = BinanceSpotTestnetHybridBroker(
        api_key="test-key",
        api_secret="test-secret",
        public_market_data=public_market_data,
    )

    candles = broker.fetch_closed_candles("BTC/USDT", interval="1h", limit=240)

    assert len(candles) == 240
    assert public_market_data.calls == [("BTC/USDT", "1h", 240)]
    assert broker.base_url == "https://testnet.binance.vision"
