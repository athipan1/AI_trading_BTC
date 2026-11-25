"""Phase 5.7.4 API/dashboard compatibility and independent monitor persistence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.research.candidate_v2_watchdog import CandidateV2Watchdog
from app.research.promotion_observability import PromotionGateObservability
from app.research.research_operations import ResearchOperationsProjection
from scripts.run_phase574_monitor import _monitor_lock, run_once

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "deploy/hermes3d/overlay/src/features/trading/ResearchOperationsPanel.tsx"


def _projection(tmp_path: Path) -> ResearchOperationsProjection:
    return ResearchOperationsProjection(
        promotion_observability=PromotionGateObservability(tmp_path / "v1-missing.json"),
        integrity_report_path=tmp_path / "v1-integrity-missing.json",
        checkpoint_path=tmp_path / "v1-checkpoint-missing.json",
        scheduler_state_path=tmp_path / "v1-scheduler-missing.json",
        candidate_v2_health_path=tmp_path / "phase574_v2_health.json",
    )


def test_v2_api_stays_backward_compatible_when_not_installed(tmp_path: Path) -> None:
    snapshot = _projection(tmp_path).snapshot()
    assert snapshot["schema_version"] == "research_operations_schema_v1"
    assert "forward_oos" in snapshot and "promotion" in snapshot
    assert snapshot["candidate_v2"]["operational_state"] == "MISSING"
    assert snapshot["candidate_v2"]["promotion_allowed"] is False
    assert "candidate_v2" not in snapshot["forward_oos"]


def _health(*, observed_at: str) -> dict:
    return {
        "schema_version": "candidate_v2_health_v1", "phase": "5.7.4",
        "observed_at": observed_at, "operational_state": "WAITING",
        "watcher_state": "HEALTHY", "research_only": True,
        "production_mutation": False, "trade_execution": False, "promotion_allowed": False,
        "source_accumulator_state": "AWAITING_CLOSED_V2_TRADES", "issues": [],
        "integrity": {"integrity_state": "WAITING", "policy_name": "confirmed"},
        "counts": {"candidate_v2_closed": 0, "canonical_rule_based_closed": 0},
        "metrics": {"candidate_v2": None, "baseline": None},
    }


def test_v2_ops_zero_trades_are_distinct_from_v1_and_read_only(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    path = tmp_path / "phase574_v2_health.json"
    path.write_text(json.dumps(_health(observed_at=now.isoformat())), encoding="utf-8")
    result = _projection(tmp_path).snapshot()
    assert result["candidate_v2"]["operational_state"] == "WAITING"
    assert result["candidate_v2"]["watcher_state"] == "HEALTHY"
    assert result["candidate_v2"]["policy_name"] == "confirmed"
    assert result["candidate_v2"]["metrics"]["candidate_v2"] == {}
    assert result["candidate_v2"]["promotion_allowed"] is False
    assert result["safety"]["auto_production_promotion"] is False


def test_v2_api_rejects_old_or_unsafe_payload(tmp_path: Path) -> None:
    path = tmp_path / "phase574_v2_health.json"
    stale = _health(observed_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat())
    path.write_text(json.dumps(stale), encoding="utf-8")
    assert _projection(tmp_path).snapshot()["candidate_v2"]["operational_state"] == "STALE"
    stale["promotion_allowed"] = True
    path.write_text(json.dumps(stale), encoding="utf-8")
    assert _projection(tmp_path).snapshot()["candidate_v2"]["operational_state"] == "INVALID"


def test_phase574_uses_existing_hermes3d_panel_and_bilingual_tabs() -> None:
    source = PANEL.read_text(encoding="utf-8")
    assert 'data-research-operations-panel' in source
    assert 'data-research-candidate-v2' in source
    assert 'setResearchTab' in source
    assert 'aria-selected={researchTab === "v2"}' in source
    assert 'ปิดออเดอร์ V2' in source
    assert 'Promotion locked (research only)' in source
    assert 'role="tablist"' in source
    assert 'max-h-[min(66dvh,34rem)]' in source


def test_independent_monitor_handles_no_watcher_or_data_without_mutation(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    args = argparse.Namespace(
        manifest=str(tmp_path / "manifest.json"),
        candidate_store=str(tmp_path / "candidate.json"),
        baseline_store=str(tmp_path / "baseline.json"),
        checkpoint=str(tmp_path / "checkpoint.json"),
        heartbeat=str(tmp_path / "heartbeat.json"),
        forward_report=str(tmp_path / "forward.json"),
        health=str(tmp_path / "phase574_v2_health.json"),
        audit_state=str(tmp_path / "phase574_v2_audit_state.json"),
        alert_state=str(tmp_path / "phase574_v2_alert_state.json"),
        line_alerts=False,
    )
    result = run_once(args, now=now)
    assert result["operational_state"] == "CRITICAL"
    assert Path(args.health).exists()
    assert not Path(args.manifest).exists()
    assert not Path(args.candidate_store).exists()
    assert not Path(args.checkpoint).exists()
    assert not Path(args.audit_state).exists()
    assert result["promotion_allowed"] is False


def test_monitor_lock_blocks_second_monitor(tmp_path: Path) -> None:
    import pytest
    path = tmp_path / "health.json"
    with _monitor_lock(path):
        with pytest.raises(RuntimeError, match="already running"):
            with _monitor_lock(path):
                pass


def test_heartbeat_contract_is_separate_from_oos_store() -> None:
    source = (ROOT / "scripts/run_phase573_fresh_oos.py").read_text(encoding="utf-8")
    assert 'phase574_v2_heartbeat.json' in source
    assert '_write_heartbeat(paths[5], result="SUCCESS"' in source
    assert 'result="ERROR"' in source
    assert CandidateV2Watchdog.HEARTBEAT_SCHEMA_VERSION == "candidate_v2_heartbeat_v1"