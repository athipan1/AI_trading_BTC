from __future__ import annotations

from typing import Any

from app.models import Candle


class MarketDataError(RuntimeError):
    pass


class MarketDataService:
    def __init__(self, exchange_id: str = "binance") -> None:
        self.exchange_id = exchange_id

    def _build_exchange(self) -> Any:
        try:
            import ccxt
        except ImportError as exc:  # pragma: no cover
            raise MarketDataError("ccxt is required for exchange market data") from exc

        exchange_cls = getattr(ccxt, self.exchange_id, None)
        if exchange_cls is None:
            raise MarketDataError(f"unsupported exchange: {self.exchange_id}")
        return exchange_cls({"enableRateLimit": True, "timeout": 15_000})

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 250) -> list[Candle]:
        exchange = self._build_exchange()
        try:
            rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as exc:  # ccxt raises exchange-specific subclasses
            raise MarketDataError(f"failed to fetch {symbol} {timeframe}: {exc}") from exc
        finally:
            close = getattr(exchange, "close", None)
            if callable(close):
                close()

        candles = [
            Candle(
                timestamp_ms=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]
        if len(candles) < 60:
            raise MarketDataError(f"insufficient market data: received {len(candles)} candles")
        if any(a.timestamp_ms >= b.timestamp_ms for a, b in zip(candles, candles[1:], strict=True)):
            raise MarketDataError("market data timestamps are not strictly increasing")
        return candles
