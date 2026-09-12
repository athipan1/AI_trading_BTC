from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.market_data.service import MarketDataError, MarketDataService
from app.models import Candle


class HistoricalMarketDataService(MarketDataService):
    """Paginated public OHLCV loader for offline research only."""

    _TIMEFRAME_RE = re.compile(r"^(?P<count>\d+)(?P<unit>[mhd])$")
    _UNIT_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}

    @classmethod
    def timeframe_ms(cls, timeframe: str) -> int:
        match = cls._TIMEFRAME_RE.fullmatch(timeframe.strip().lower())
        if match is None:
            raise ValueError(f"unsupported historical timeframe: {timeframe}")
        return int(match.group("count")) * cls._UNIT_MS[match.group("unit")]

    @classmethod
    def integrity_report(
        cls,
        candles: list[Candle],
        *,
        timeframe: str,
        since_ms: int,
        until_ms: int,
    ) -> dict[str, Any]:
        if until_ms <= since_ms:
            raise ValueError("until_ms must be after since_ms")
        interval_ms = cls.timeframe_ms(timeframe)
        timestamps = [int(candle.timestamp_ms) for candle in candles]
        counts = Counter(timestamps)
        duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
        out_of_order_count = sum(
            1 for previous, current in zip(timestamps, timestamps[1:], strict=False) if current <= previous
        )
        expected_timestamps = range(since_ms, until_ms, interval_ms)
        timestamp_set = set(timestamps)
        missing = [timestamp for timestamp in expected_timestamps if timestamp not in timestamp_set]
        expected_count = len(range(since_ms, until_ms, interval_ms))
        first_expected = since_ms if expected_count else None
        last_expected = since_ms + (expected_count - 1) * interval_ms if expected_count else None
        first_actual = timestamps[0] if timestamps else None
        last_actual = timestamps[-1] if timestamps else None
        strict_ordering = duplicate_count == 0 and out_of_order_count == 0
        complete_range = (
            bool(timestamps)
            and first_actual == first_expected
            and last_actual == last_expected
            and not missing
            and strict_ordering
        )
        return {
            "timeframe": timeframe,
            "interval_ms": interval_ms,
            "requested_since_ms": since_ms,
            "requested_until_ms": until_ms,
            "expected_candles": expected_count,
            "actual_candles": len(candles),
            "first_expected_timestamp_ms": first_expected,
            "last_expected_timestamp_ms": last_expected,
            "first_actual_timestamp_ms": first_actual,
            "last_actual_timestamp_ms": last_actual,
            "first_timestamp_match": first_actual == first_expected,
            "last_timestamp_match": last_actual == last_expected,
            "strict_timestamp_ordering": strict_ordering,
            "duplicate_timestamps": duplicate_count,
            "out_of_order_timestamps": out_of_order_count,
            "missing_interval_count": len(missing),
            "missing_interval_timestamps_ms": missing[:100],
            "missing_interval_list_truncated": len(missing) > 100,
            "complete_range": complete_range,
        }

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
        self.timeframe_ms(timeframe)
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
                    if timestamp_ms < since_ms:
                        continue
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
            for previous, current in zip(candles, candles[1:], strict=False)
        ):
            raise MarketDataError("historical timestamps are not strictly increasing")
        return candles
