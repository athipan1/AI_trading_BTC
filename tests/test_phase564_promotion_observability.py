from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations.hermes3d.router import build_hermes3d_router
from app.monitoring.position_store import PositionStore
from app.research.promotion_observability import PromotionGateObservability
from app.research.router import build_research_router


def _report() -> dict[str, object]:
    return {
        "schema_version": "oos_promotion_gate_schema_v1",
        "phase": "5.6.3",
        "research_only": True,
        "production_position_store_mutated": False,
        "production_execution_mutated": False,
        "optimization_performed": False,
        "oos_retuning_performed": False,
        "method": "deterministic_frozen_oos_evidence_promotion_gate",
        "state": "TOO_EARLY",
        "evidence_state": "TOO_EARLY",
        "promotion_allowed": False,
        "next_state": None,
        "auto_production_promotion": False,
        "rejection_reasons": [],
        "gate_manifest": {
            "performance_gate": {
                "minimum_oos_signals": 20,
                "minimum_policy_selected_trades": 10,
            }
        },
        "sample_gate": {
            "ready": False,
            "signals": 8,
            "policy_selected_trades": 6,
            "checks": {
                "minimum_oos_signals": False,
                "minimum_policy_selected_trades": False,
            },
        },
        "structural_gate": {"passed": True, "checks": {}},
        "performance_gate": {"evaluated": False, "passed": False, "checks": {}},
        "superiority_gate": {"evaluated": False, "passed": False, "checks": {}},
        "safety": {
            "model_frozen": True,
            "policy_frozen": True,
            "threshold_frozen": True,
            "fresh_oos": True,
            "chronological_integrity": True,
            "feature_leakage_free": True,
            "production_isolation": True,
        },
    }


def _write_report(path: Path) -> datetime:
    path.write_text(json.dumps(_report()), encoding="utf-8")
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def test_missing_artifact_is_operational_not_strategy_failure(tmp_path: Path) -> None:
    reader = PromotionGateObservability(tmp_path / "missing.json")

    payload = reader.snapshot()

    assert payload["operational_state"] == "MISSING"
    assert payload["decision"] is None
    assert payload["research_only"] is True
    assert payload["trade_execution"] is False


def test_invalid_artifact_is_reported_without_recomputing_gate(tmp_path: Path) -> None:
    path = tmp_path / "phase563.json"
    path.write_text("{broken", encoding="utf-8")
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    reader = PromotionGateObservability(path, now_factory=lambda: modified_at)

    payload = reader.snapshot()

    assert payload["operational_state"] == "INVALID"
    assert payload["decision"] is None
    assert "unable to read" in payload["error"]


def test_healthy_projection_preserves_authoritative_gate_decision(tmp_path: Path) -> None:
    path = tmp_path / "phase563.json"
    modified_at = _write_report(path)
    reader = PromotionGateObservability(
        path,
        now_factory=lambda: modified_at + timedelta(seconds=60),
    )

    payload = reader.snapshot()

    assert payload["operational_state"] == "HEALTHY"
    assert payload["decision"]["state"] == "TOO_EARLY"
    assert payload["decision"]["promotion_allowed"] is False
    assert payload["evidence"]["signals"] == {"current": 8, "required": 20}
    assert payload["evidence"]["policy_selected_trades"] == {"current": 6, "required": 10}
    assert payload["gates"] == {
        "structural": "PASS",
        "performance": "WAITING",
        "superiority": "WAITING",
    }
    assert payload["frozen_contract"] == {
        "model": True,
        "policy": True,
        "threshold": True,
    }
    assert payload["safety"]["production_execution_mutated"] is False


def test_stale_artifact_is_operational_state_only(tmp_path: Path) -> None:
    path = tmp_path / "phase563.json"
    modified_at = _write_report(path)
    reader = PromotionGateObservability(
        path,
        stale_after_seconds=100,
        now_factory=lambda: modified_at + timedelta(seconds=200),
    )

    payload = reader.snapshot()

    assert payload["operational_state"] == "STALE"
    assert payload["decision"]["state"] == "TOO_EARLY"
    assert payload["decision"]["promotion_allowed"] is False


def test_research_endpoint_is_read_only_projection(tmp_path: Path) -> None:
    path = tmp_path / "phase563.json"
    modified_at = _write_report(path)
    reader = PromotionGateObservability(path, now_factory=lambda: modified_at)
    app = FastAPI()
    app.include_router(
        build_research_router(
            spot_position_store=PositionStore(tmp_path / "spot.json"),
            futures_position_store=PositionStore(tmp_path / "futures.json"),
            promotion_observability=reader,
        )
    )

    response = TestClient(app).get("/research/promotion")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"]["state"] == "TOO_EARLY"
    assert payload["read_only"] is True
    assert payload["trade_execution"] is False


class _HermesReader:
    def registry(self) -> dict[str, object]:
        return {"agents": []}

    def state(self) -> dict[str, object]:
        return {"status": "ok"}


def test_hermes_state_exposes_same_read_only_promotion_projection(tmp_path: Path) -> None:
    path = tmp_path / "phase563.json"
    modified_at = _write_report(path)
    reader = PromotionGateObservability(path, now_factory=lambda: modified_at)
    app = FastAPI()
    app.include_router(build_hermes3d_router(_HermesReader(), promotion_reader=reader))

    response = TestClient(app).get("/state")

    assert response.status_code == 200
    promotion = response.json()["research_promotion"]
    assert promotion["decision"]["state"] == "TOO_EARLY"
    assert promotion["evidence"]["signals"]["current"] == 8
    assert promotion["trade_execution"] is False
