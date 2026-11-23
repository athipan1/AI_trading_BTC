"""Public, unauthenticated Binance Spot candles for Termux research.

This service deliberately cannot submit orders or use private exchange keys.
It implements the HistoricalMarketDataService fetch_range contract.
"""

from __future__ import annotations

from typing import Any

import requests

from app.market_data.service import MarketDataError
from app.models import Candle
from app.research.historical_market_data import HistoricalMarketDataService


class BinancePublicOHLCV(HistoricalMarketDataService):
    """Read only BTC/USDT H1 data from Binance's market-data-only host."""

    BASE_URL = "https://data-api.binance.vision/api/v3/klines"
    INTERVAL_MS = 3_600_000

    def __init__(self, *, session: Any | None = None, timeout_seconds: int = 20) -> None:
        super().__init__("binance")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.session = session if session is not None else requests.Session()
        self.timeout_seconds = timeout_seconds

    def fetch_range(
        self,
        symbol: str,
        timeframe: str,
        *,
        since_ms: int,
        until_ms: int,
        page_limit: int = 1000,
    ) -> list[Candle]:
        if symbol != "BTC/USDT" or timeframe != "1h":
            raise ValueError("Phase 5.7.3 only supports Binance Spot BTC/USDT 1h")
        if since_ms < 0 or until_ms <= since_ms:
            raise ValueError("invalid candle range")
        if since_ms % self.INTERVAL_MS or until_ms % self.INTERVAL_MS:
            raise ValueError("range must align to closed UTC H1 candle boundaries")
        if not 1 <= page_limit <= 1000:
            raise ValueError("Binance page limit must be in [1, 1000]")

        result: list[Candle] = []
        cursor = since_ms
        while cursor < until_ms:
            try:
                response = self.session.get(
                    self.BASE_URL,
                    params={
                        "symbol": "BTCUSDT",
                        "interval": "1h",
                        "startTime": cursor,
                        "endTime": until_ms - 1,
                        "limit": page_limit,
                    },
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                rows: Any = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise MarketDataError(f"Binance public OHLCV fetch failed: {exc}") from exc
            if not isinstance(rows, list):
                raise MarketDataError("Binance public OHLCV returned a non-list response")
            if not rows:
                break
            last = cursor - self.INTERVAL_MS
            for row in rows:
                try:
                    if not isinstance(row, list) or len(row) < 7:
                        raise ValueError("invalid kline shape")
                    timestamp = int(row[0])
                    if timestamp < cursor or timestamp >= until_ms:
                        raise ValueError("kline timestamp outside requested page")
                    if timestamp % self.INTERVAL_MS or timestamp <= last:
                        raise ValueError("kline timestamps not increasing/UTC-aligned")
                    if int(row[6]) != timestamp + self.INTERVAL_MS - 1:
                        raise ValueError("kline close timestamp is invalid")
                    candle = Candle(
                        timestamp_ms=timestamp,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                    if candle.low > min(candle.open, candle.close) or (
                        candle.high < max(candle.open, candle.close)
                    ):
                        raise ValueError("invalid OHLC candle price bounds")
                except (ValueError, TypeError) as exc:
                    raise MarketDataError(f"invalid public OHLCV row: {exc}") from exc
                last = timestamp
                result.append(candle)
            next_cursor = last + self.INTERVAL_MS
            if next_cursor <= cursor:
                raise MarketDataError("OHLCV pagination did not advance")
            cursor = next_cursor
            if len(rows) < page_limit:
                break
        return result