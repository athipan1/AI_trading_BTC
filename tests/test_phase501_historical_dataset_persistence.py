from __future__ import annotations

from pathlib import Path

from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.historical_store import HistoricalResearchStore
from app.research.trade_dataset import ResearchTradeDatasetProjection


def historical_trade(index: int) -> dict[str, object]:
    opened_hour = index % 24
    opened_day = 1 + index // 24
    created_at = f"2026-07-{opened_day:02d}T{opened_hour:02d}:00:00+00:00"
    closed_at = f"2026-07-{opened_day:02d}T{opened_hour:02d}:30:00+00:00"
    return {
        "order_id": f"hist-triple_ema-{index:04d}",
        "strategy_id": "triple_ema",
        "symbol": "BTC/USDT",
        "side": "buy",
        "status": "CLOSED",
        "created_at": created_at,
        "closed_at": closed_at,
        "entry_price": 100.0,
        "entry_fill_price": 100.02,
        "quantity": 0.1,
        "initial_stop_loss": 95.0,
        "initial_risk_price_distance": 5.02,
        "initial_risk_usdt": 0.502,
        "entry_market_regime": "BULL_TREND",
        "trade_path_highest_price": 110.0,
        "trade_path_lowest_price": 98.0,
        "trade_path_observation_count": 6,
        "exit_reason": "STRATEGY_EXIT",
        "exit_price": 108.0,
        "exit_fill_price": 107.98,
        "holding_seconds": 1800.0,
        "mae_usdt": 0.202,
        "mfe_usdt": 0.998,
        "mae_r": 0.4023904382,
        "mfe_r": 1.9880478088,
        "gross_realized_pnl": 0.796,
        "net_realized_pnl": 0.7752,
        "realized_r": 1.5442231076,
        "entry_commission_usdt": 0.010002,
        "exit_commission_usdt": 0.010798,
        "total_commission_usdt": 0.0208,
        "mfe_capture_ratio": 0.7767,
        "profit_giveback_r": 0.4438,
        "mae_utilization_r": 0.4024,
    }


def replay_payload(count: int) -> dict[str, object]:
    return {
        "schema_version": "historical_replay_schema_v1",
        "trades": [historical_trade(index) for index in range(count)],
    }


def test_historical_store_is_persistent_and_idempotent(tmp_path: Path) -> None:
    store = HistoricalResearchStore(tmp_path / "research" / "historical-trades.json")

    first = store.upsert_replay(replay_payload(2), dataset_run_id="run-1")
    second = store.upsert_replay(replay_payload(2), dataset_run_id="run-1")

    assert first == {"inserted": 2, "updated": 0, "total": 2}
    assert second == {"inserted": 0, "updated": 0, "total": 2}
    rows = store.load()
    assert len(rows) == 2
    assert rows[0]["data_origin"] == "historical_replay"
    assert rows[0]["dataset_run_id"] == "run-1"


def test_historical_trades_flow_through_canonical_research_schema(tmp_path: Path) -> None:
    store = HistoricalResearchStore(tmp_path / "historical.json")
    store.upsert_replay(replay_payload(1), dataset_run_id="run-1")

    dataset = ResearchTradeDatasetProjection.build(
        [], historical_trades=store.load(), source="historical"
    )

    assert dataset["schema_version"] == "research_trade_schema_v2"
    assert dataset["metadata"]["qualified_trades"] == 1
    assert dataset["metadata"]["data_origins"] == ["historical_replay"]
    assert dataset["rows"][0]["data_origin"] == "historical_replay"
    assert dataset["rows"][0]["slippage_cost_usdt"] > 0


def test_historical_dataset_reaches_quality_and_training_readiness(tmp_path: Path) -> None:
    store = HistoricalResearchStore(tmp_path / "historical.json")
    store.upsert_replay(replay_payload(30), dataset_run_id="run-30")
    historical = store.load()

    quality = ResearchFeatureDatasetProjection.quality(
        [], historical_trades=historical, source="historical"
    )
    split = ResearchFeatureDatasetProjection.temporal_split(
        [], historical_trades=historical, source="historical"
    )

    assert quality["sample_size"] == 30
    assert quality["quality"]["leakage_check"]["status"] == "PASS"
    assert quality["readiness"] == {
        "pipeline": "READY",
        "dataset": "READY",
        "training": "READY",
    }
    assert split["counts"] == {"train": 21, "validation": 4, "test": 5}
    assert split["random_shuffle"] is False
    assert split["readiness"] == "READY"
