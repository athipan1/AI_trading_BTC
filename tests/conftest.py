from __future__ import annotations

import pytest

from app.models import Candle


@pytest.fixture
def trend_candles() -> list[Candle]:
    candles: list[Candle] = []
    price = 50_000.0
    for i in range(120):
        drift = 80 if i % 3 else -25
        open_price = price
        close = price + drift
        candles.append(
            Candle(
                timestamp_ms=1_700_000_000_000 + i * 3_600_000,
                open=open_price,
                high=max(open_price, close) + 60,
                low=min(open_price, close) - 60,
                close=close,
                volume=100 + i,
            )
        )
        price = close
    return candles
