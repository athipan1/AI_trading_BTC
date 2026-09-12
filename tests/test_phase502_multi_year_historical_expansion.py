from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.models import Candle
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.historical_diagnostics import HistoricalResearchDiagnostics
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_store import HistoricalResearchStore


HOUR_MS = 3_600_000


def candle(timestamp_ms: int) -> Candle:
    return Candle(
        timestamp_ms=timestamp_ms,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
    )


def historical_trade(index: int) -> dict[str, object]:
    opened = datetime(2021, 1, 1, tzinfo=UTC) + timedelta(days=index * 70)
    closed = opened + timedelta(hours=6)
    side = "buy" if index % 2 == 0 else "sell"
    regime = ("BULL_TREND", "BEAR_TREND", "SIDEWAYS")[index % 3]
    realized_r = 1.2 if index % 3 == 0 else -0.6 if index % 3 == 1 else 0.0
    return {
        "order_id": f"hist-phase502-{index:04d}",
        "strategy_id": "triple_ema" if side == "buy" else "triple_ema_short",
        "symbol": "BTC/USDT",
        "side": side,
        "status": "CLOSED",
        "created_at": opened.isoformat(),
        "closed_at": closed.isoformat(),
        "entry_price": 100.0,
        "entry_fill_price": 100.02,
        "quantity": 0.1,
        "initial_stop_loss": 95.0 if side == "buy" else 105.0,
        "initial_risk_price_distance": 5.02,
        "initial_risk_usdt": 0.502,
        "entry_market_regime": regime,
        "trade_path_highest_price": 110.0,
        "trade_path_lowest_price": 92.0,
        "trade_path_observation_count": 6,
        "exit_reason": "STRATEGY_EXIT",
        "exit_price": 108.0,
        "exit_fill_price": 107.98,
        "holding_seconds": 21_600.0,
        "mae_usdt": 0.202,
        "mfe_usdt": 0.998,
        "mae_r": 0.4023904382,
        "mfe_r": 1.9880478088,
        "gross_realized_pnl": 0.796,
        "net_realized_pnl": 0.7752,
        "realized_r": realized_r,
        "entry_commission_usdt": 0.010002,
        "exit_commission_usdt": 0.010798,
        "total_commission_usdt": 0.0208,
        "mfe_capture_ratio": 0.7767,
        "profit_giveback_r": 0.4438,
        "mae_utilization_r": 0.4024,
    }


def test_h1_integrity_report_detects_gaps_without_hiding_them() -> None:
    candles = [candle(0), candle(HOUR_MS), candle(3 * HOUR_MS)]

    report = HistoricalMarketDataService.integrity_report(
        candles,
        timeframe="1h",
        since_ms=0,
        until_ms=4 * HOUR_MS,
    )

    assert report["expected_candles"] == 4
    assert report["actual_candles"] == 3
    assert report["strict_timestamp_ordering"] is True
    assert report["duplicate_timestamps"] == 0
    assert report["missing_interval_count"] == 1
    assert report["missing_interval_timestamps_ms"] == [2 * HOUR_MS]
    assert report["complete_range"] is False


def test_integrity_report_flags_duplicates_and_out_of_order_rows() -> None:
    candles = [candle(0), candle(HOUR_MS), candle(HOUR_MS), candle(3 * HOUR_MS)]

    report = HistoricalMarketDataService.integrity_report(
        candles,
        timeframe="1h",
        since_ms=0,
        until_ms=4 * HOUR_MS,
    )

    assert report["duplicate_timestamps"] == 1
    assert report["out_of_order_timestamps"] == 1
    assert report["strict_timestamp_ordering"] is False


def test_multi_year_diagnostics_report_strategy_regime_side_and_year_coverage() -> None:
    trades = [historical_trade(index) for index in range(30)]

    report = HistoricalResearchDiagnostics.build(trades)

    assert report["sample_size"] == 30
    assert report["invalid_rows"] == 0
    assert report["duplicate_order_ids"] == 0
    assert report["coverage"]["calendar_year_count"] >= 5
    assert report["coverage"]["regime_count"] == 3
    assert set(report["coverage"]["strategies"]) == {"triple_ema", "triple_ema_short"}
    assert report["coverage"]["sides"] == {"buy": 15, "sell": 15}
    assert report["outcomes"] == {"wins": 10, "losses": 10, "breakeven": 10}
    assert report["distributions"]["realized_r"]["median"] is not None


def test_phase502_preserves_idempotency_and_chronological_split(tmp_path: Path) -> None:
    trades = [historical_trade(index) for index in range(30)]
    replay = {"schema_version": "historical_replay_schema_v1", "trades": trades}
    store = HistoricalResearchStore(tmp_path / "historical-phase502.json")

    first = store.upsert_replay(replay, dataset_run_id="phase502")
    second = store.upsert_replay(replay, dataset_run_id="phase502")
    stored = store.load()
    quality = ResearchFeatureDatasetProjection.quality(
        [], historical_trades=stored, source="historical"
    )
    split = ResearchFeatureDatasetProjection.temporal_split(
        [], historical_trades=stored, source="historical"
    )

    assert first == {"inserted": 30, "updated": 0, "total": 30}
    assert second == {"inserted": 0, "updated": 0, "total": 30}
    assert quality["quality"]["duplicate_order_ids"] == 0
    assert quality["quality"]["invalid_rows"] == 0
    assert quality["quality"]["feature_coverage_pct"] >= 95.0
    assert quality["quality"]["leakage_check"]["status"] == "PASS"
    assert quality["readiness"]["dataset"] == "READY"
    assert split["counts"] == {"train": 21, "validation": 4, "test": 5}
    assert split["checks"] == {
        "order_id_overlap": "PASS",
        "chronological_order": "PASS",
    }
    assert split["readiness"] == "READY"
    assert split["time_bounds"]["train"]["last"] <= split["time_bounds"]["validation"]["first"]
    assert split["time_bounds"]["validation"]["last"] <= split["time_bounds"]["test"]["first"]
