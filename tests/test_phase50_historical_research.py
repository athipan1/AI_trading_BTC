from __future__ import annotations

from typing import Any

from app.models import Candle, MarketRegime, TradeAction, TradeSignal
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import HistoricalReplayConfig, HistoricalStrategyReplay


class StubStrategy:
    strategy_id = "stub"
    min_candles = 2

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal:
        if len(candles) == 2:
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.BUY,
                confidence=1.0,
                regime=MarketRegime.BULL_TREND,
                entry_price=candles[-1].close,
                stop_loss=candles[-1].close - 10,
            )
        if len(candles) >= 4:
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.EXIT,
                confidence=1.0,
                regime=MarketRegime.BULL_TREND,
                stop_loss=candles[-1].close - 10,
            )
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            action=TradeAction.HOLD,
            confidence=1.0,
            regime=MarketRegime.BULL_TREND,
            stop_loss=candles[-1].close - 10,
        )


class StubExchange:
    def __init__(self, rows: list[list[Any]]) -> None:
        self.rows = rows
        self.closed = False

    def fetch_ohlcv(
        self,
        symbol: str,
        *,
        timeframe: str,
        since: int,
        limit: int,
    ) -> list[list[Any]]:
        del symbol, timeframe, since, limit
        return self.rows

    def close(self) -> None:
        self.closed = True


class StubHistoricalMarketDataService(HistoricalMarketDataService):
    def __init__(self, exchange: StubExchange) -> None:
        super().__init__()
        self.exchange = exchange

    def _build_exchange(self) -> StubExchange:
        return self.exchange


def candle(index: int, price: float) -> Candle:
    return Candle(
        timestamp_ms=index * 3_600_000,
        open=price,
        high=price + 5,
        low=price - 5,
        close=price,
        volume=1,
    )


def test_historical_fetch_range_accepts_multiple_ordered_candles() -> None:
    rows = [
        [3_600_000, 100, 105, 95, 101, 1],
        [7_200_000, 101, 106, 96, 102, 1],
        [10_800_000, 102, 107, 97, 103, 1],
    ]
    exchange = StubExchange(rows)
    service = StubHistoricalMarketDataService(exchange)

    result = service.fetch_range(
        "BTC/USDT",
        "1h",
        since_ms=0,
        until_ms=14_400_000,
        page_limit=1000,
    )

    assert [item.timestamp_ms for item in result] == [3_600_000, 7_200_000, 10_800_000]
    assert exchange.closed is True


def test_replay_uses_next_candle_fill_and_isolated_store() -> None:
    candles = [candle(1, 100), candle(2, 110), candle(3, 120), candle(4, 130), candle(5, 140)]
    replay = HistoricalStrategyReplay(
        HistoricalReplayConfig(quantity=1, fee_rate=0, slippage_bps=0)
    ).replay(candles, StubStrategy())
    assert replay["production_position_store_mutated"] is False
    assert replay["closed_trades"] == 1
    trade = replay["trades"][0]
    assert trade["entry_price"] == 110
    assert trade["entry_fill_price"] == 120
    assert trade["exit_fill_price"] == 140
    assert trade["entry_market_regime"] == "BULL_TREND"
    assert trade["initial_risk_usdt"] > 0
    assert trade["trade_path_observation_count"] >= 1
    assert trade["net_realized_pnl"] == 20
    assert trade["realized_r"] is not None


def test_replay_rejects_insufficient_history() -> None:
    replay = HistoricalStrategyReplay()
    try:
        replay.replay([candle(1, 100), candle(2, 101)], StubStrategy())
    except ValueError as exc:
        assert "requires more than" in str(exc)
    else:
        raise AssertionError("expected ValueError")
