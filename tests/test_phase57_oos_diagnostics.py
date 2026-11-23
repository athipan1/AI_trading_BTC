"""Contract tests for read-only, deterministic Phase 5.7.1 diagnostics."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.research.oos_diagnostics import OOSPromotionDiagnostics


def _promotion(*, evaluated: bool = True) -> dict[str, object]:
    frozen_pin = {
        "manifest_hash": "manifest-1",
        "policy_hash": "policy-1",
        "model_fingerprint": "model-1",
        "discovery_cutoff": "2026-09-01T00:00:00+00:00",
    }
    gate_manifest = {
        "schema_version": "oos_promotion_gate_manifest_v1",
        "phase": "5.6.3",
        "source_frozen_contract": frozen_pin,
        "performance_gate": {
            "minimum_oos_signals": 20,
            "minimum_policy_selected_trades": 10,
            "minimum_policy_profit_factor": 1.0,
            "require_positive_policy_expectancy": True,
            "require_policy_drawdown_not_worse_than_global_ml": True,
        },
    }
    gate_manifest["gate_manifest_hash"] = OOSPromotionDiagnostics._hash(gate_manifest)
    return {
        "schema_version": "oos_promotion_gate_schema_v1",
        "phase": "5.6.3",
        "research_only": True,
        "state": "REJECT" if evaluated else "TOO_EARLY",
        "promotion_allowed": False,
        "production_position_store_mutated": False,
        "production_execution_mutated": False,
        "optimization_performed": False,
        "oos_retuning_performed": False,
        "auto_production_promotion": False,
        "rejection_reasons": ["PERFORMANCE_ACCEPTANCE_FAILED"] if evaluated else [],
        "gate_manifest": gate_manifest,
        "sample_gate": {
            "signals": 50 if evaluated else 8,
            "policy_selected_trades": 40 if evaluated else 3,
            "ready": evaluated,
            "checks": {
                "minimum_oos_signals": evaluated,
                "minimum_policy_selected_trades": evaluated,
            },
        },
        "structural_gate": {
            "passed": True,
            "checks": {
                "model_frozen": True,
                "fresh_oos": True,
                "oos_retuning": False,
                "production_isolation": True,
            },
        },
        "performance_gate": {
            "evaluated": evaluated,
            "passed": False,
            "checks": {
                "policy_expectancy_positive": False,
                "policy_profit_factor": False,
                "policy_drawdown": True,
            },
            "policy_metrics": {
                "trade_count": 40,
                "expectancy_r": -0.20,
                "profit_factor": 0.8,
                "max_drawdown_r": 8.0,
                "total_realized_r": -8.0,
                "win_rate_pct": 40.0,
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
                "trade_count": 20,
                "expectancy_r": -0.3,
                "max_drawdown_r": 10.0,
                "total_realized_r": -9.0,
            },
        },
    }


def _integrity(*, healthy: bool = True) -> dict[str, object]:
    return {
        "schema_version": "evidence_integrity_schema_v1",
        "state": "PASS" if healthy else "FAIL",
        "operational_state": "HEALTHY" if healthy else "STALE",
        "integrity_ok": healthy,
    }


def test_rejected_gate_has_explicit_root_checks_without_reevaluation() -> None:
    promotion = _promotion()
    untouched = copy.deepcopy(promotion)

    report = OOSPromotionDiagnostics.analyze(promotion, integrity=_integrity())

    assert promotion == untouched
    assert report["promotion_state_unchanged"] == "REJECT"
    assert report["evidence_trust"] == "VERIFIED_HEALTHY"
    assert report["blocking_checks"]["performance"] == [
        "policy_expectancy_positive", "policy_profit_factor"
    ]
    assert report["blocking_checks"]["structural"] == []
    assert report["blocking_checks"]["superiority"] == []
    assert report["gate_diagnostics"]["structural"]["statuses"]["oos_retuning"] == "PASS"
    assert report["gate_diagnostics"]["superiority"]["statuses"][
        "policy_total_r_ge_global_ml"
    ] == "NOT_EVALUATED"
    assert report["metric_comparison"]["observed_deltas_not_new_gates"][
        "profit_factor_minus_required"
    ] == pytest.approx(-0.2)
    assert report["auto_production_promotion"] is False
    assert report["candidate_v2_research_plan"]["production_activation"] == "NOT_AUTHORIZED"


def test_too_early_is_not_reported_as_evaluated_performance_failure() -> None:
    report = OOSPromotionDiagnostics.analyze(_promotion(evaluated=False))
    assert report["blocking_checks"]["evidence"] == [
        "minimum_oos_signals", "minimum_policy_selected_trades"
    ]
    assert report["blocking_checks"]["performance"] == []
    assert report["gate_diagnostics"]["performance"]["evaluated"] is False
    assert report["evidence_trust"] == "NOT_VERIFIED"


def test_broken_manifest_hash_fails_closed() -> None:
    promotion = _promotion()
    promotion["gate_manifest"]["performance_gate"]["minimum_policy_profit_factor"] = 0.1
    with pytest.raises(ValueError, match="hash mismatch"):
        OOSPromotionDiagnostics.analyze(promotion)


@pytest.mark.parametrize(
    "flag",
    [
        "production_position_store_mutated",
        "production_execution_mutated",
        "optimization_performed",
        "oos_retuning_performed",
        "auto_production_promotion",
    ],
)
def test_unsafe_report_fails_closed(flag: str) -> None:
    promotion = _promotion()
    promotion[flag] = True
    with pytest.raises(ValueError, match="unsafe or missing"):
        OOSPromotionDiagnostics.analyze(promotion)


def test_incomplete_gate_checks_report_unknown() -> None:
    promotion = _promotion()
    promotion["performance_gate"]["checks"]["policy_drawdown"] = None
    report = OOSPromotionDiagnostics.analyze(promotion)
    assert report["blocking_checks"]["performance"] == [
        "policy_expectancy_positive", "policy_profit_factor", "policy_drawdown"
    ]
    assert report["gate_diagnostics"]["performance"]["unknown"] == ["policy_drawdown"]


def test_integrity_failure_remains_visible_without_rewriting_evidence() -> None:
    report = OOSPromotionDiagnostics.analyze(_promotion(), integrity=_integrity(healthy=False))
    assert report["evidence_trust"] == "BLOCKED_INTEGRITY"
    assert report["production_mutation"] is False


def test_verified_milestones_maintain_hash_chain() -> None:
    from app.research.oos_milestones import OOSMilestoneEvidenceHistory

    promotion = _promotion()
    pin = OOSMilestoneEvidenceHistory._candidate_pin(promotion)
    entry = {
        "milestone_signals": 20,
        "observed_signals": 20,
        "capture_mode": "EXACT",
        "performance_gate": {
            "policy_metrics": {"expectancy_r": -0.4, "profit_factor": 0.7, "max_drawdown_r": 9.0}
        },
        "promotion": {"state": "REJECT"},
        "previous_snapshot_hash": None,
    }
    entry["snapshot_hash"] = OOSMilestoneEvidenceHistory._canonical_hash(entry)
    history = {
        "schema_version": "oos_milestone_evidence_history_v1",
        "phase": "5.6.8",
        "milestone_targets": [20, 50, 100],
        "candidate_pin": pin,
        "milestones": [entry],
    }
    report = OOSPromotionDiagnostics.analyze(promotion, milestone_history=history)
    assert report["verified_milestones"][0]["profit_factor"] == pytest.approx(0.7)

    history["milestones"][0]["profit_factor"] = 999
    with pytest.raises(ValueError, match="hash"):
        OOSPromotionDiagnostics.analyze(promotion, milestone_history=history)


def test_cli_blocks_overwriting_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import run_phase57_oos_diagnostics as command

    path = tmp_path / "promotion.json"
    original = json.dumps(_promotion())
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["phase57", "--promotion", str(path), "--output", str(path)]
    )
    with pytest.raises(ValueError, match="cannot replace"):
        command.main()
    assert path.read_text(encoding="utf-8") == original


def test_cli_creates_only_separate_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import run_phase57_oos_diagnostics as command

    input_path = tmp_path / "promotion.json"
    output_path = tmp_path / "diagnostic.json"
    original = json.dumps(_promotion())
    input_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["phase57", "--promotion", str(input_path), "--output", str(output_path)]
    )
    assert command.main() == 0
    assert input_path.read_text(encoding="utf-8") == original
    assert json.loads(output_path.read_text(encoding="utf-8"))["phase"] == "5.7.1"