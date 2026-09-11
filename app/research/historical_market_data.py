from __future__ import annotations

from typing import Any

from app.market_data.service import MarketDataError, MarketDataService
from app.models import Candle


class HistoricalMarketDataService(MarketDataService):
    """Paginated public OHLCV loader for offline research only."""

    def fetch_range(
        self,
        symbol: str,
        timeframe: str,
        *,
        since_ms: int,
        until_ms: int,
        page_limit: int = 1000,
    ) -> list[Candle]:
        if since_ms < 0 or until_ms <= since_ms:
            raise ValueError("invalid historical time range")
        if not 1 <= page_limit <= 1000:
            raise ValueError("page_limit must be between 1 and 1000")
        exchange = self._build_exchange()
        candles: list[Candle] = []
        cursor = since_ms
        try:
            while cursor < until_ms:
                try:
                    rows: list[list[Any]] = exchange.fetch_ohlcv(
                        symbol,
                        timeframe=timeframe,
                        since=cursor,
                        limit=page_limit,
                    )
                except Exception as exc:
                    raise MarketDataError(
                        f"failed historical fetch {symbol} {timeframe} since={cursor}: {exc}"
                    ) from exc
                if not rows:
                    break
                added = 0
                for row in rows:
                    timestamp_ms = int(row[0])
                    if timestamp_ms >= until_ms:
                        break
                    if candles and timestamp_ms <= candles[-1].timestamp_ms:
                        continue
                    candles.append(
                        Candle(
                            timestamp_ms=timestamp_ms,
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                            volume=float(row[5]),
                        )
                    )
                    added += 1
                last_timestamp = int(rows[-1][0])
                next_cursor = last_timestamp + 1
                if next_cursor <= cursor or added == 0 and last_timestamp < cursor:
                    raise MarketDataError("historical pagination made no forward progress")
                cursor = next_cursor
                if len(rows) < page_limit:
                    break
        finally:
            close = getattr(exchange, "close", None)
            if callable(close):
                close()
        if any(
            previous.timestamp_ms >= current.timestamp_ms
            for previous, current in zip(candles, candles[1:])
        ):
            raise MarketDataError("historical timestamps are not strictly increasing")
        return candles
