from __future__ import annotations

from app.models import Candle, MarketRegime, TradeAction, TradeSignal
from app.research.entry_features import (
    ADVANCED_ENTRY_NUMERIC_FEATURES,
    ENTRY_FEATURE_SCHEMA_VERSION,
    build_entry_time_features,
)
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.historical_replay import HistoricalStrategyReplay


def _candles(count: int) -> list[Candle]:
    candles: list[Candle] = []
    for index in range(count):
        base = 30_000.0 + index * 10.0
        candles.append(
            Candle(
                timestamp_ms=1_700_000_000_000 + index * 3_600_000,
                open=base,
                high=base + 30.0,
                low=base - 20.0,
                close=base + 10.0,
                volume=100.0 + (index % 20) * 5.0,
            )
        )
    return candles


class _OneTradeStrategy:
    strategy_id = "phase51_test"
    min_candles = 200

    def analyze(self, candles: list[Candle], symbol: str, timeframe: str) -> TradeSignal:
        if len(candles) == 200:
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.BUY,
                confidence=1.0,
                regime=MarketRegime.BULL_TREND,
                entry_price=candles[-1].close,
                stop_loss=candles[-1].close - 100.0,
                take_profit=candles[-1].close + 200.0,
                risk_reward=2.0,
                reasons=["phase51-test-entry"],
            )
        if len(candles) == 201:
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.EXIT,
                confidence=1.0,
                regime=MarketRegime.BULL_TREND,
                reasons=["phase51-test-exit"],
            )
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            action=TradeAction.HOLD,
            confidence=0.0,
            regime=MarketRegime.BULL_TREND,
            reasons=["phase51-test-hold"],
        )


def test_entry_feature_extractor_is_decision_time_only() -> None:
    history = _candles(205)
    snapshot = build_entry_time_features(history)

    assert tuple(snapshot) == ADVANCED_ENTRY_NUMERIC_FEATURES
    assert snapshot["decision_close"] == history[-1].close
    assert snapshot["rsi_14"] is not None
    assert snapshot["atr_pct"] is not None
    assert snapshot["ema200_distance_pct"] is not None
    assert snapshot["return_24h"] is not None
    assert snapshot["rolling_volatility_24h"] is not None
    assert snapshot["close_location"] is not None


def test_historical_replay_captures_snapshot_before_next_candle_execution() -> None:
    replay = HistoricalStrategyReplay().replay(_candles(202), _OneTradeStrategy())

    assert replay["production_position_store_mutated"] is False
    assert replay["closed_trades"] == 1
    trade = replay["trades"][0]
    assert trade["entry_feature_schema_version"] == ENTRY_FEATURE_SCHEMA_VERSION
    assert trade["decision_at"] < trade["created_at"]
    assert trade["entry_feature_timestamp_ms"] < trade["opened_at_ms"]
    assert trade["entry_features"]["decision_close"] == _candles(200)[-1].close


def test_historical_feature_projection_reports_advanced_readiness() -> None:
    replay = HistoricalStrategyReplay().replay(_candles(202), _OneTradeStrategy())
    trades = replay["trades"]

    dataset = ResearchFeatureDatasetProjection.build(
        [], historical_trades=trades, source="historical"
    )
    quality = ResearchFeatureDatasetProjection.quality(
        [], historical_trades=trades, source="historical"
    )

    row = dataset["rows"][0]
    assert row["feature_available_at"] == trades[0]["decision_at"]
    assert row["execution_time"] == trades[0]["created_at"]
    assert row["features"]["rsi_14"] is not None
    assert quality["quality"]["advanced_feature_row_coverage_pct"] == 100.0
    assert quality["quality"]["advanced_feature_coverage_pct"] >= 95.0
    assert quality["quality"]["temporal_integrity"]["status"] == "PASS"
    assert quality["quality"]["leakage_check"]["status"] == "PASS"
    assert quality["readiness"]["advanced_entry_features"] == "READY"


def test_temporal_guard_rejects_feature_snapshot_after_execution() -> None:
    replay = HistoricalStrategyReplay().replay(_candles(202), _OneTradeStrategy())
    trade = dict(replay["trades"][0])
    trade["decision_at"] = "2099-01-01T00:00:00+00:00"

    quality = ResearchFeatureDatasetProjection.quality(
        [], historical_trades=[trade], source="historical"
    )

    assert quality["quality"]["temporal_integrity"]["status"] == "FAIL"
    assert quality["readiness"]["dataset"] == "NOT_READY"
