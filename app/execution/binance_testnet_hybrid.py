from __future__ import annotations

from urllib.parse import urlparse

import requests

from app.execution.binance_testnet import BinanceTestnetBroker
from app.models import Candle


class BinancePublicMarketDataSafetyError(RuntimeError):
    """Raised when public market data is pointed at an unexpected host."""


class BinancePublicMarketData:
    """Read-only Binance Spot public market-data client for strategy analysis."""

    BASE_URL = "https://api.binance.com"
    ALLOWED_HOST = "api.binance.com"
    INTERVAL_MS = BinanceTestnetBroker.INTERVAL_MS

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self._assert_public_url(self.base_url)

    @classmethod
    def _assert_public_url(cls, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != cls.ALLOWED_HOST:
            raise BinancePublicMarketDataSafetyError(
                f"refusing market-data URL: expected https://{cls.ALLOWED_HOST}"
            )

    @staticmethod
    def _exchange_symbol(symbol: str) -> str:
        normalized = symbol.upper().strip()
        if normalized.count("/") != 1:
            raise ValueError("symbol must use BASE/QUOTE format, for example BTC/USDT")
        base, quote = normalized.split("/", 1)
        if not base.isalnum() or not quote.isalnum():
            raise ValueError("symbol contains unsupported characters")
        return f"{base}{quote}"

    def _request(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> dict | list:
        url = f"{self.base_url}{path}"
        self._assert_public_url(url)
        try:
            response = self.session.request(
                "GET",
                url,
                params=dict(params or {}),
                timeout=10,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Binance public market-data network error: {exc.__class__.__name__}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Binance public market data returned non-JSON HTTP {response.status_code}"
            ) from exc

        if not response.ok:
            code = payload.get("code") if isinstance(payload, dict) else None
            message = payload.get("msg") if isinstance(payload, dict) else None
            raise RuntimeError(
                f"Binance public market-data API error HTTP {response.status_code}: "
                f"code={code} msg={message}"
            )
        if not isinstance(payload, (dict, list)):
            raise RuntimeError("Binance public market data returned an unexpected response shape")
        return payload

    def _server_time_ms(self) -> int:
        payload = self._request("/api/v3/time")
        if not isinstance(payload, dict):
            raise RuntimeError("Binance public market data returned invalid server time payload")
        server_time = payload.get("serverTime")
        if not isinstance(server_time, int) or server_time <= 0:
            raise RuntimeError("Binance public market data did not return a valid server time")
        return server_time

    def fetch_closed_candles(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 240,
    ) -> list[Candle]:
        if interval not in self.INTERVAL_MS:
            raise ValueError(f"unsupported Binance public interval: {interval}")
        if not 60 <= limit <= 1000:
            raise ValueError("candle limit must be between 60 and 1000")

        exchange_symbol = self._exchange_symbol(symbol)
        server_time = self._server_time_ms()
        payload = self._request(
            "/api/v3/klines",
            params={
                "symbol": exchange_symbol,
                "interval": interval,
                "limit": min(limit + 2, 1000),
            },
        )
        if not isinstance(payload, list):
            raise RuntimeError("Binance public market data returned invalid kline payload")

        candles: list[Candle] = []
        last_close_time: int | None = None
        for row in payload:
            if not isinstance(row, list) or len(row) < 7:
                raise RuntimeError("Binance public market data returned malformed kline data")
            close_time = int(row[6])
            if close_time >= server_time:
                continue
            candles.append(
                Candle(
                    timestamp_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
            last_close_time = close_time

        candles = candles[-limit:]
        if len(candles) < limit or last_close_time is None:
            raise RuntimeError(
                f"Binance public market data returned only {len(candles)} of {limit} "
                "required closed candles"
            )

        timestamps = [candle.timestamp_ms for candle in candles]
        if any(
            current <= previous
            for previous, current in zip(timestamps, timestamps[1:], strict=False)
        ):
            raise RuntimeError("Binance public market-data candles are not strictly increasing")

        freshness_limit = self.INTERVAL_MS[interval] * 2 + 60_000
        if server_time - last_close_time > freshness_limit:
            raise RuntimeError("latest closed Binance public candle is stale")
        return candles


class BinanceSpotTestnetHybridBroker(BinanceTestnetBroker):
    """Execute on Spot Testnet while sourcing strategy candles from Binance public Spot."""

    def __init__(
        self,
        *args: object,
        public_market_data: BinancePublicMarketData | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.public_market_data = public_market_data or BinancePublicMarketData()

    def fetch_closed_candles(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 240,
    ) -> list[Candle]:
        return self.public_market_data.fetch_closed_candles(
            symbol,
            interval=interval,
            limit=limit,
        )
