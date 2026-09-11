from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.monitoring.position_store import PositionStore
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.router import build_research_router


def _trade(order_id: str, *, opened_hour: int = 0) -> dict[str, object]:
    return {
        "order_id": order_id,
        "strategy_id": "triple_ema_short",
        "symbol": "BTC/USDT",
        "side": "sell",
        "status": "CLOSED",
        "reconciliation_status": "RECONCILED",
        "created_at": f"2026-09-10T{opened_hour:02d}:00:00+00:00",
        "closed_at": f"2026-09-10T{opened_hour:02d}:30:00+00:00",
        "entry_price": 100.0,
        "entry_fill_price": 100.1,
        "entry_filled_quantity": 0.1,
        "quantity": 0.1,
        "initial_stop_loss": 110.0,
        "initial_stop_loss_source": "entry_snapshot",
        "initial_risk_price_distance": 10.0,
        "initial_risk_usdt": 1.0,
        "initial_risk_source": "entry_snapshot",
        "entry_market_regime": "BEAR_TREND",
        "trade_path_highest_price": 104.0,
        "trade_path_lowest_price": 80.0,
        "trade_path_observation_count": 10,
        "exit_reason": "TAKE_PROFIT",
        "exit_price": 85.0,
        "exit_fill_price": 85.1,
        "exit_filled_quantity": 0.1,
        "entry_commission_quote_equivalent": 0.01,
        "exit_commission_quote_equivalent": 0.01,
        "gross_realized_pnl": 1.5,
        "net_realized_pnl": 1.48,
    }


def test_feature_contract_keeps_outcome_fields_out_of_model_features() -> None:
    result = ResearchFeatureDatasetProjection.build([_trade("one")])

    contract = result["feature_contract"]
    assert "entry_market_regime" in contract["model_features"]
    assert "realized_r" not in contract["model_features"]
    assert "mfe_r" not in contract["model_features"]
    assert result["rows"][0]["features"]["side_direction"] == -1.0
    assert result["rows"][0]["features"]["entry_stop_distance_pct"] == 10.0


def test_leakage_guard_rejects_outcome_fields() -> None:
    result = ResearchFeatureDatasetProjection.validate_feature_names(
        ["entry_price", "realized_r", "mfe_r"]
    )

    assert result["status"] == "FAIL"
    assert result["forbidden_features"] == ["mfe_r", "realized_r"]


def test_quality_separates_pipeline_dataset_and_training_readiness() -> None:
    result = ResearchFeatureDatasetProjection.quality([_trade("one")])

    assert result["readiness"]["pipeline"] == "READY"
    assert result["readiness"]["dataset"] == "READY"
    assert result["readiness"]["training"] == "NOT_READY"
    assert result["quality"]["feature_coverage_pct"] == 100.0
    assert result["quality"]["leakage_check"]["status"] == "PASS"


def test_temporal_split_is_chronological_and_never_random() -> None:
    positions = [_trade(f"trade-{index:02d}", opened_hour=index) for index in range(20)]
    result = ResearchFeatureDatasetProjection.temporal_split(positions)

    assert result["random_shuffle"] is False
    assert result["counts"] == {"train": 14, "validation": 3, "test": 3}
    assert result["order_ids"]["train"][0] == "trade-00"
    assert result["order_ids"]["test"][-1] == "trade-19"
    assert result["readiness"] == "NOT_READY"


def test_research_router_exposes_phase49_endpoints(tmp_path: Path) -> None:
    spot = PositionStore(tmp_path / "spot.json")
    futures = PositionStore(tmp_path / "futures.json")
    futures.save([_trade("short-one")])

    app = FastAPI()
    app.include_router(
        build_research_router(
            spot_position_store=spot,
            futures_position_store=futures,
        )
    )
    client = TestClient(app)

    features = client.get("/research/features")
    quality = client.get("/research/dataset-quality")
    split = client.get("/research/dataset-split")

    assert features.status_code == 200
    assert quality.status_code == 200
    assert split.status_code == 200
    assert features.json()["schema_version"] == "research_feature_schema_v1"
    assert quality.json()["readiness"]["training"] == "NOT_READY"
    assert split.json()["random_shuffle"] is False
