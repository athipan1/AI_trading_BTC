from __future__ import annotations

from app.models import Candle, MarketRegime, TradeAction, TradeSignal
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import HistoricalReplayConfig, HistoricalStrategyReplay


HOUR_MS = 3_600_000


class GapAwareStubStrategy:
    strategy_id = "gap_aware_stub"
    min_candles = 2

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal:
        if len(candles) == 2:
            action = TradeAction.BUY
        elif len(candles) >= 4:
            action = TradeAction.EXIT
        else:
            action = TradeAction.HOLD
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            action=action,
            confidence=1.0,
            regime=MarketRegime.BULL_TREND,
            entry_price=candles[-1].close,
            stop_loss=candles[-1].close - 10,
        )


def candle(hour: int, price: float = 100.0) -> Candle:
    return Candle(
        timestamp_ms=hour * HOUR_MS,
        open=price,
        high=price + 5,
        low=price - 5,
        close=price,
        volume=1.0,
    )


def test_integrity_marks_ordered_source_gaps_safe_for_segment_replay() -> None:
    candles = [candle(0), candle(1), candle(3), candle(4)]

    report = HistoricalMarketDataService.integrity_report(
        candles,
        timeframe="1h",
        since_ms=0,
        until_ms=5 * HOUR_MS,
    )

    assert report["complete_range"] is False
    assert report["segment_replay_safe"] is True
    assert report["missing_interval_count"] == 1
    assert report["missing_interval_timestamps_ms"] == [2 * HOUR_MS]


def test_contiguous_segments_split_gaps_without_synthetic_candles() -> None:
    candles = [candle(0), candle(1), candle(2), candle(5), candle(6), candle(7)]

    segments = HistoricalMarketDataService.contiguous_segments(candles, timeframe="1h")

    assert [[item.timestamp_ms for item in segment] for segment in segments] == [
        [0, HOUR_MS, 2 * HOUR_MS],
        [5 * HOUR_MS, 6 * HOUR_MS, 7 * HOUR_MS],
    ]
    assert sum(len(segment) for segment in segments) == len(candles)


def test_segmented_replay_resets_state_and_never_carries_position_across_gap() -> None:
    candles = [
        candle(0, 100),
        candle(1, 110),
        candle(2, 120),
        candle(5, 200),
        candle(6, 210),
        candle(7, 220),
        candle(8, 230),
        candle(9, 240),
    ]
    segments = HistoricalMarketDataService.contiguous_segments(candles, timeframe="1h")
    replay = HistoricalStrategyReplay(
        HistoricalReplayConfig(quantity=1, fee_rate=0, slippage_bps=0)
    ).replay_segments(segments, GapAwareStubStrategy())

    assert replay["gap_policy"] == "segment"
    assert replay["segment_count"] == 2
    assert replay["replayed_segment_count"] == 2
    assert replay["skipped_segment_count"] == 0
    assert replay["source_candles"] == len(candles)
    assert replay["production_position_store_mutated"] is False
    assert replay["closed_trades"] == 1
    trade = replay["trades"][0]
    assert trade["opened_at_ms"] == 7 * HOUR_MS
    assert trade["closed_at"].startswith("1970-01-01T09:00:00")


def test_segmented_replay_skips_segments_that_cannot_rewarm_strategy() -> None:
    segments = [
        [candle(0), candle(1)],
        [candle(5), candle(6), candle(7), candle(8), candle(9)],
    ]
    replay = HistoricalStrategyReplay(
        HistoricalReplayConfig(quantity=1, fee_rate=0, slippage_bps=0)
    ).replay_segments(segments, GapAwareStubStrategy())

    assert replay["segment_count"] == 2
    assert replay["replayed_segment_count"] == 1
    assert replay["skipped_segment_count"] == 1
    assert replay["closed_trades"] == 1
