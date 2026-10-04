from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.research.oos_milestones import OOSMilestoneEvidenceHistory
from app.research.promotion_observability import PromotionGateObservability
from app.research.research_operations import ResearchOperationsProjection

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "deploy/hermes3d/overlay/src/features/trading/ResearchOperationsPanel.tsx"


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _promotion(*, signals: int, selected: int, state: str = "REJECT") -> dict[str, object]:
    return {
        "schema_version": "oos_promotion_gate_schema_v1",
        "phase": "5.6.3",
        "research_only": True,
        "state": state,
        "evidence_state": "EVIDENCE_READY" if signals >= 20 and selected >= 10 else "TOO_EARLY",
        "promotion_allowed": state == "ACCEPT",
        "next_state": "PRODUCTION_CANDIDATE" if state == "ACCEPT" else None,
        "rejection_reasons": ["PERFORMANCE_ACCEPTANCE_FAILED"] if state == "REJECT" else [],
        "gate_manifest": {
            "gate_manifest_hash": "gate-hash",
            "performance_gate": {
                "minimum_oos_signals": 20,
                "minimum_policy_selected_trades": 10,
            },
            "source_frozen_contract": {
                "manifest_hash": "manifest-hash",
                "policy_hash": "policy-hash",
                "model_fingerprint": "model-hash",
                "discovery_cutoff": "2026-09-01T00:00:00+00:00",
            },
        },
        "sample_gate": {
            "ready": signals >= 20 and selected >= 10,
            "signals": signals,
            "policy_selected_trades": selected,
        },
        "structural_gate": {
            "passed": True,
            "checks": {"model_frozen": True, "policy_frozen": True},
        },
        "performance_gate": {
            "evaluated": signals >= 20,
            "passed": False,
            "checks": {
                "policy_drawdown": False,
                "policy_expectancy_positive": False,
                "policy_profit_factor": False,
            },
            "policy_metrics": {
                "available_signals": signals,
                "expectancy_r": -1.4402489716713258,
                "max_drawdown_r": 22.18008073050362,
                "profit_factor": 0.2175767003760876,
                "selection_rate_pct": 65.0,
                "total_realized_r": -18.723236631727236,
                "trade_count": selected,
                "win_rate_pct": 30.76923076923077,
            },
        },
        "superiority_gate": {
            "evaluated": False,
            "passed": False,
            "checks": {
                "policy_expectancy_ge_global_ml": True,
                "policy_total_r_ge_global_ml": False,
            },
            "global_ml_metrics": {
                "available_signals": signals,
                "expectancy_r": -2.2566402234889473,
                "max_drawdown_r": 19.253325663199014,
                "profit_factor": 0.17954529826417615,
                "selection_rate_pct": 35.0,
                "total_realized_r": -15.796481564422631,
                "trade_count": 7,
                "win_rate_pct": 14.285714285714285,
            },
        },
        "safety": {
            "model_frozen": True,
            "policy_frozen": True,
            "threshold_frozen": True,
        },
        "production_position_store_mutated": False,
        "production_execution_mutated": False,
        "optimization_performed": False,
        "oos_retuning_performed": False,
        "auto_production_promotion": False,
    }


def _integrity(
    *,
    passed: bool = True,
    operational_state: str = "HEALTHY",
) -> dict[str, object]:
    return {
        "schema_version": "evidence_integrity_schema_v1",
        "phase": "5.6.5",
        "state": "PASS" if passed else "FAIL",
        "operational_state": operational_state,
        "integrity_ok": passed,
    }


def _checkpoint(*, signals: int, run_count: int = 24) -> dict[str, object]:
    return {
        "schema_version": "forward_oos_checkpoint_schema_v1",
        "phase": "5.6.2",
        "last_processed_until": "2026-10-04T09:00:00+00:00",
        "last_oos_trade_count": signals,
        "last_evidence_stage": "EARLY_SIGNAL" if signals < 50 else "INTERMEDIATE",
        "last_state": "FAIL",
        "run_count": run_count,
    }


def _paths(tmp_path: Path, *, signals: int, selected: int = 13) -> tuple[Path, Path, Path, Path]:
    promotion = tmp_path / "promotion.json"
    integrity = tmp_path / "integrity.json"
    checkpoint = tmp_path / "checkpoint.json"
    history = tmp_path / "history.json"
    _write(promotion, _promotion(signals=signals, selected=selected))
    _write(integrity, _integrity())
    _write(checkpoint, _checkpoint(signals=signals))
    return promotion, integrity, checkpoint, history


def test_phase568_records_exact_20_signal_snapshot(tmp_path: Path) -> None:
    promotion, integrity, checkpoint, history = _paths(tmp_path, signals=20)
    recorder = OOSMilestoneEvidenceHistory(
        now_factory=lambda: datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
    )

    result = recorder.record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )

    assert result["state"] == "RECORDED"
    assert result["recorded_milestones"] == [20]
    assert result["next_milestone"] == 50
    payload = json.loads(history.read_text(encoding="utf-8"))
    assert payload["phase"] == "5.6.8"
    assert payload["append_only"] is True
    assert payload["safety"]["oos_retuning_performed"] is False
    snapshot = payload["milestones"][0]
    assert snapshot["milestone_signals"] == 20
    assert snapshot["observed_signals"] == 20
    assert snapshot["capture_mode"] == "EXACT"
    assert snapshot["promotion"]["state"] == "REJECT"
    assert snapshot["performance_gate"]["policy_metrics"]["expectancy_r"] < 0
    assert snapshot["snapshot_hash"]


def test_phase568_repeated_run_is_idempotent_and_preserves_bytes(tmp_path: Path) -> None:
    promotion, integrity, checkpoint, history = _paths(tmp_path, signals=20)
    recorder = OOSMilestoneEvidenceHistory(
        now_factory=lambda: datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
    )
    recorder.record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )
    before = history.read_bytes()

    result = recorder.record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )

    assert result["state"] == "NO_MILESTONE_DUE"
    assert result["recorded_milestones"] == []
    assert history.read_bytes() == before


def test_phase568_appends_50_without_changing_20(tmp_path: Path) -> None:
    promotion, integrity, checkpoint, history = _paths(tmp_path, signals=20)
    recorder = OOSMilestoneEvidenceHistory(
        now_factory=lambda: datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
    )
    recorder.record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )
    first = json.loads(history.read_text(encoding="utf-8"))["milestones"][0]

    _write(promotion, _promotion(signals=50, selected=30, state="CONTINUE_ACCUMULATING"))
    _write(checkpoint, _checkpoint(signals=50, run_count=60))
    result = recorder.record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )

    payload = json.loads(history.read_text(encoding="utf-8"))
    assert result["recorded_milestones"] == [50]
    assert payload["milestones"][0] == first
    second = payload["milestones"][1]
    assert second["milestone_signals"] == 50
    assert second["previous_snapshot_hash"] == first["snapshot_hash"]


def test_phase568_backfill_is_explicit_when_threshold_was_crossed(tmp_path: Path) -> None:
    promotion, integrity, checkpoint, history = _paths(tmp_path, signals=51, selected=31)
    recorder = OOSMilestoneEvidenceHistory()

    result = recorder.record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )

    assert result["recorded_milestones"] == [20, 50]
    payload = json.loads(history.read_text(encoding="utf-8"))
    assert [entry["capture_mode"] for entry in payload["milestones"]] == [
        "BACKFILL_AT_OR_AFTER_MILESTONE",
        "BACKFILL_AT_OR_AFTER_MILESTONE",
    ]
    assert all(entry["observed_signals"] == 51 for entry in payload["milestones"])


def test_phase568_integrity_failure_does_not_mutate_history(tmp_path: Path) -> None:
    promotion, integrity, checkpoint, history = _paths(tmp_path, signals=20)
    _write(integrity, _integrity(passed=False))

    result = OOSMilestoneEvidenceHistory().record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )

    assert result["state"] == "BLOCKED_INTEGRITY"
    assert result["history_mutated"] is False
    assert not history.exists()


def test_phase568_stale_integrity_does_not_mutate_history(tmp_path: Path) -> None:
    promotion, integrity, checkpoint, history = _paths(tmp_path, signals=20)
    _write(integrity, _integrity(operational_state="STALE"))

    result = OOSMilestoneEvidenceHistory().record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )

    assert result["state"] == "BLOCKED_INTEGRITY"
    assert result["history_mutated"] is False
    assert not history.exists()


def test_phase568_rejects_candidate_pin_change_and_tampering(tmp_path: Path) -> None:
    promotion, integrity, checkpoint, history = _paths(tmp_path, signals=20)
    recorder = OOSMilestoneEvidenceHistory()
    recorder.record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )

    changed = _promotion(signals=50, selected=30)
    gate_manifest = changed["gate_manifest"]
    assert isinstance(gate_manifest, dict)
    source = gate_manifest["source_frozen_contract"]
    assert isinstance(source, dict)
    source["policy_hash"] = "different-policy"
    _write(promotion, changed)
    with pytest.raises(ValueError, match="candidate pin differs"):
        recorder.record(
            promotion_path=promotion,
            integrity_path=integrity,
            checkpoint_path=checkpoint,
            history_path=history,
        )

    _write(promotion, _promotion(signals=50, selected=30))
    payload = json.loads(history.read_text(encoding="utf-8"))
    payload["milestones"][0]["promotion"]["state"] = "ACCEPT"
    _write(history, payload)
    with pytest.raises(ValueError, match="snapshot hash is invalid"):
        recorder.record(
            promotion_path=promotion,
            integrity_path=integrity,
            checkpoint_path=checkpoint,
            history_path=history,
        )


def test_phase568_daily_wiring_runs_after_promotion_before_line_alert() -> None:
    script = Path("scripts/run_phase562_daily.sh").read_text(encoding="utf-8")

    phase563 = script.index("scripts/run_phase563_oos_promotion_gate.py")
    phase568 = script.index("scripts/run_phase568_oos_milestone_history.py")
    phase566 = script.index("scripts/run_phase566_oos_line_alert.py")

    assert phase563 < phase568 < phase566
    assert "phase568_oos_milestones.json" in script


def test_phase568_is_projected_into_research_operations_and_ui(tmp_path: Path) -> None:
    promotion, integrity, checkpoint, history = _paths(tmp_path, signals=20)
    recorder = OOSMilestoneEvidenceHistory(
        now_factory=lambda: datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
    )
    recorder.record(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
        history_path=history,
    )

    scheduler = tmp_path / "scheduler.json"
    _write(
        scheduler,
        {
            "schema_version": "phase562_daily_scheduler_state_v1",
            "timezone": "Asia/Bangkok",
            "scheduled_local_time": "07:10",
            "last_attempt_at": "2026-10-04T07:10:00+07:00",
            "last_return_code": 0,
            "last_result": "SUCCESS",
            "last_run_local_date": "2026-10-04",
        },
    )
    modified_at = datetime.fromtimestamp(promotion.stat().st_mtime, tz=UTC)
    projection = ResearchOperationsProjection(
        promotion_observability=PromotionGateObservability(
            promotion,
            now_factory=lambda: modified_at,
        ),
        integrity_report_path=integrity,
        checkpoint_path=checkpoint,
        milestone_history_path=history,
        scheduler_state_path=scheduler,
    )

    snapshot = projection.snapshot()

    assert snapshot["operational_state"] == "HEALTHY"
    journey = snapshot["milestone_evidence"]
    assert journey["operational_state"] == "HEALTHY"
    assert journey["targets"] == [20, 50, 100]
    assert journey["recorded_count"] == 1
    assert journey["next_target"] == 50
    assert journey["milestones"][0]["promotion"]["state"] == "REJECT"

    panel = PANEL.read_text(encoding="utf-8")
    assert "data-oos-evidence-journey" in panel
    assert "data-oos-milestone" in panel
    assert 'evidenceJourney: "เส้นทางหลักฐาน OOS"' in panel
    assert 'evidenceJourney: "OOS Evidence Journey"' in panel
