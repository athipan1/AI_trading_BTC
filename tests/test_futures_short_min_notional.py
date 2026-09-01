from __future__ import annotations

from pathlib import Path

import pytest

from app.auto_trading.futures_short_engine import FuturesShortAutoTrader
from app.auto_trading.state_store import AutoTradeStateStore
from app.execution.binance_futures_testnet import BinanceFuturesTestnetBroker
from app.models import Candle
from app.monitoring.position_store import PositionStore
from app.risk.engine import RiskEngine
from app.strategies.triple_ema_short import TripleEMAShortStrategy


def _bearish_candles() -> list[Candle]:
    closes = [120.0] * 150 + [110.0] * 30 + [100.0] * 20 + [98.0]
    return [
        Candle(
            timestamp_ms=index * 3_600_000,
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=1.0,
        )
        for index, close in enumerate(closes)
    ]


class FakeFuturesBroker:
    def __init__(self) -> None:
        self.order_calls = 0

    def fetch_closed_candles(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[Candle]:
        return _bearish_candles()

    def account_snapshot(self, symbol: str) -> dict[str, float]:
        return {
            "margin_balance_usdt": 5_000.0,
            "available_balance_usdt": 5_000.0,
        }

    def minimum_entry_notional(self, symbol: str) -> float:
        return 50.0

    def place_market_short(self, symbol: str, notional_usdt: float) -> dict:
        self.order_calls += 1
        raise AssertionError("order must not be submitted below minimum notional")


def test_demo_broker_rejects_hard_cap_below_entry_minimum() -> None:
    with pytest.raises(ValueError, match="at least 50.00 USDT"):
        BinanceFuturesTestnetBroker("key", "secret", max_order_notional_usdt=25.0)


def test_market_min_notional_never_below_demo_floor() -> None:
    market = {
        "filters": [
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ]
    }
    minimum = BinanceFuturesTestnetBroker._market_min_notional(market)
    assert float(minimum) == 50.0


def test_short_entry_below_minimum_is_skipped_without_order_attempt(tmp_path: Path) -> None:
    broker = FakeFuturesBroker()
    state_store = AutoTradeStateStore(tmp_path / "short-state.json")
    trader = FuturesShortAutoTrader(
        broker=broker,  # type: ignore[arg-type]
        strategy=TripleEMAShortStrategy(),
        risk_engine=RiskEngine(risk_per_trade_pct=0.005),
        position_store=PositionStore(tmp_path / "positions.json"),
        state_store=state_store,
        notifier=None,
        entry_notional_usdt=40.0,
        candle_limit=201,
    )

    result = trader.run_once()

    assert result["event"] == "ENTRY_SKIPPED_MIN_NOTIONAL"
    assert result["minimum_notional_usdt"] == 50.0
    assert broker.order_calls == 0
    state = state_store.load()
    assert state["halted"] is False
    assert state["order_attempt"] is None
