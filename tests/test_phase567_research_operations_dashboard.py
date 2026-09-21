from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.monitoring.position_store import PositionStore
from app.research.promotion_observability import PromotionGateObservability
from app.research.research_operations import ResearchOperationsProjection
from app.research.router import build_research_router

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "deploy/hermes3d/overlay/src/features/trading/ResearchOperationsPanel.tsx"
OFFICE_PAGE = ROOT / "deploy/hermes3d/overlay/src/app/office/page.tsx"
PROXY = ROOT / "deploy/hermes3d/overlay/src/app/api/trading-runtime/route.ts"


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _promotion() -> dict[str, object]:
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
            "signals": 9,
            "policy_selected_trades": 7,
            "checks": {
                "minimum_oos_signals": False,
                "minimum_policy_selected_trades": False,
            },
        },
        "structural_gate": {"passed": True},
        "performance_gate": {"evaluated": False, "passed": False},
        "superiority_gate": {"evaluated": False, "passed": False},
        "safety": {
            "model_frozen": True,
            "policy_frozen": True,
            "threshold_frozen": True,
        },
    }


def _projection(tmp_path: Path) -> ResearchOperationsProjection:
    promotion = tmp_path / "phase563.json"
    integrity = tmp_path / "phase565.json"
    checkpoint = tmp_path / "phase562-checkpoint.json"
    scheduler = tmp_path / "scheduler.json"

    _write(promotion, _promotion())
    modified_at = datetime.fromtimestamp(promotion.stat().st_mtime, tz=UTC)
    _write(
        integrity,
        {
            "schema_version": "evidence_integrity_schema_v1",
            "phase": "5.6.5",
            "state": "PASS",
            "operational_state": "HEALTHY",
            "integrity_ok": True,
            "checks": {"order_ids_unique": True},
            "violations": {},
            "evidence": {"oos_trade_count": 7},
        },
    )
    _write(
        checkpoint,
        {
            "schema_version": "forward_oos_checkpoint_schema_v1",
            "phase": "5.6.2",
            "last_processed_until": "2026-09-21T14:00:00+00:00",
            "last_oos_trade_count": 7,
            "last_evidence_stage": "TOO_EARLY",
            "last_state": "TOO_EARLY",
            "run_count": 11,
        },
    )
    _write(
        scheduler,
        {
            "schema_version": "phase562_daily_scheduler_state_v1",
            "timezone": "Asia/Bangkok",
            "scheduled_local_time": "07:10",
            "last_attempt_at": "2026-09-21T07:10:00+07:00",
            "last_attempt_local_date": "2026-09-21",
            "last_return_code": 0,
            "last_result": "SUCCESS",
            "last_run_local_date": "2026-09-21",
        },
    )
    return ResearchOperationsProjection(
        promotion_observability=PromotionGateObservability(
            promotion,
            now_factory=lambda: modified_at,
        ),
        integrity_report_path=integrity,
        checkpoint_path=checkpoint,
        scheduler_state_path=scheduler,
    )


def test_phase567_combines_authoritative_read_only_artifacts(tmp_path: Path) -> None:
    payload = _projection(tmp_path).snapshot()

    assert payload["phase"] == "5.6.7"
    assert payload["schema_version"] == "research_operations_schema_v1"
    assert payload["operational_state"] == "HEALTHY"
    assert payload["forward_oos"]["signals"] == {"current": 9, "required": 20}
    assert payload["forward_oos"]["policy_selected_trades"] == {"current": 7, "required": 10}
    assert payload["forward_oos"]["run_count"] == 11
    assert payload["integrity"]["state"] == "PASS"
    assert payload["promotion"]["state"] == "TOO_EARLY"
    assert payload["promotion"]["promotion_allowed"] is False
    assert payload["frozen_contract"] == {
        "model": True,
        "policy": True,
        "threshold": True,
    }
    assert payload["scheduler"]["last_result"] == "SUCCESS"
    assert payload["safety"]["auto_production_promotion"] is False
    assert payload["trade_execution"] is False
    assert payload["production_mutation"] is False


def test_phase567_missing_artifacts_degrade_observability_without_mutation(tmp_path: Path) -> None:
    promotion = tmp_path / "promotion.json"
    _write(promotion, _promotion())
    modified_at = datetime.fromtimestamp(promotion.stat().st_mtime, tz=UTC)
    projection = ResearchOperationsProjection(
        promotion_observability=PromotionGateObservability(
            promotion,
            now_factory=lambda: modified_at,
        ),
        integrity_report_path=tmp_path / "missing-integrity.json",
        checkpoint_path=tmp_path / "missing-checkpoint.json",
        scheduler_state_path=tmp_path / "missing-scheduler.json",
    )

    payload = projection.snapshot()

    assert payload["operational_state"] == "MISSING"
    assert payload["integrity"]["operational_state"] == "MISSING"
    assert payload["forward_oos"]["operational_state"] == "MISSING"
    assert payload["scheduler"]["operational_state"] == "MISSING"
    assert payload["safety"]["production_position_store_mutated"] is False
    assert payload["safety"]["production_execution_mutated"] is False


def test_phase567_integrity_failure_is_visible_but_not_recomputed(tmp_path: Path) -> None:
    projection = _projection(tmp_path)
    integrity_path = projection.integrity_report_path
    _write(
        integrity_path,
        {
            "schema_version": "evidence_integrity_schema_v1",
            "phase": "5.6.5",
            "state": "FAIL",
            "operational_state": "HEALTHY",
            "integrity_ok": False,
            "checks": {"order_ids_unique": False},
            "violations": {"duplicate_order_ids": ["dup"]},
            "evidence": {"oos_trade_count": 7},
        },
    )

    payload = projection.snapshot()

    assert payload["operational_state"] == "DEGRADED"
    assert payload["integrity"]["state"] == "FAIL"
    assert payload["integrity"]["checks"]["order_ids_unique"] is False
    assert payload["promotion"]["state"] == "TOO_EARLY"


def test_phase567_research_endpoint_exposes_single_operations_snapshot(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(
        build_research_router(
            spot_position_store=PositionStore(tmp_path / "spot.json"),
            futures_position_store=PositionStore(tmp_path / "futures.json"),
            operations_observability=_projection(tmp_path),
        )
    )

    response = TestClient(app).get("/research/operations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["phase"] == "5.6.7"
    assert payload["read_only"] is True
    assert payload["trade_execution"] is False


def test_phase567_hermes_panel_is_read_only_bilingual_and_uses_single_endpoint() -> None:
    panel = PANEL.read_text(encoding="utf-8")
    office = OFFICE_PAGE.read_text(encoding="utf-8")
    proxy = PROXY.read_text(encoding="utf-8")

    assert 'const OPERATIONS_URL = "/api/trading-runtime?resource=research-operations"' in panel
    assert 'title: "ศูนย์ปฏิบัติการ Research"' in panel
    assert 'title: "Research Operations"' in panel
    assert "data-forward-oos-metrics" in panel
    assert "data-frozen-research-contract" in panel
    assert "data-research-scheduler" in panel
    assert 'import { ResearchOperationsPanel } from "@/features/trading/ResearchOperationsPanel"' in office
    assert "<ResearchOperationsPanel />" in office
    assert '"research-operations"' in proxy
    assert '"/research/operations"' in proxy
    assert all(
        forbidden not in panel.lower()
        for forbidden in (
            "binance_api_key",
            "binance_api_secret",
            "create_order",
            "cancel_order",
            "ccxt",
        )
    )
