from __future__ import annotations

from pathlib import Path

import pytest

from app.research.oos_promotion_gate import OOSPromotionGate


def _frozen_manifest() -> dict[str, object]:
    return {
        "manifest_hash": "manifest-1",
        "policy_hash": "policy-1",
        "model_fingerprint": "model-1",
        "discovery_cutoff": "2026-08-30T15:00:00+00:00",
    }


def _validation_config() -> dict[str, object]:
    return {
        "minimum_oos_signals": 20,
        "minimum_policy_selected_trades": 10,
        "minimum_policy_profit_factor": 1.0,
        "require_positive_policy_expectancy": True,
        "require_policy_drawdown_not_worse_than_global_ml": True,
    }


def _validation(
    *,
    sample_ready: bool,
    performance_pass: bool = True,
    superiority_pass: bool = True,
) -> dict[str, object]:
    return {
        "config": _validation_config(),
        "oos": {"signals": 20 if sample_ready else 8},
        "comparison": {
            "frozen_regime_policy": {
                "trade_count": 10 if sample_ready else 4,
                "expectancy_r": 0.20,
                "profit_factor": 1.4,
                "max_drawdown_r": 2.0,
                "total_realized_r": 2.0,
            },
            "global_ml": {
                "trade_count": 9,
                "expectancy_r": 0.10,
                "profit_factor": 1.2,
                "max_drawdown_r": 2.5,
                "total_realized_r": 1.0,
            },
        },
        "structural_acceptance": {
            "manifest_integrity": True,
            "model_frozen": True,
            "threshold_frozen": True,
            "policy_frozen": True,
            "oos_retuning": False,
            "fresh_oos": True,
            "chronological_integrity": True,
            "feature_leakage": True,
            "production_isolation": True,
        },
        "evidence_acceptance": {
            "minimum_oos_signals": sample_ready,
            "minimum_policy_selected_trades": sample_ready,
        },
        "performance_acceptance": {
            "policy_expectancy_positive": performance_pass,
            "policy_profit_factor": performance_pass,
            "policy_drawdown": performance_pass,
        },
        "superiority": {
            "policy_expectancy_ge_global_ml": superiority_pass,
            "policy_total_r_ge_global_ml": superiority_pass,
        },
    }


def test_gate_manifest_is_frozen_and_rejects_drift(tmp_path: Path) -> None:
    gate = OOSPromotionGate()
    path = tmp_path / "gate.json"
    manifest = gate.load_or_freeze_gate_manifest(
        path,
        frozen_manifest=_frozen_manifest(),
        validation_config=_validation_config(),
    )
    assert path.exists()
    assert manifest["phase"] == "5.6.3"
    assert manifest["decision_policy"]["auto_production_promotion"] is False

    changed = _validation_config()
    changed["minimum_policy_profit_factor"] = 0.9
    with pytest.raises(ValueError, match="differs from the frozen contract"):
        gate.load_or_freeze_gate_manifest(
            path,
            frozen_manifest=_frozen_manifest(),
            validation_config=changed,
        )


def test_too_early_does_not_evaluate_or_promote() -> None:
    gate = OOSPromotionGate()
    gate_manifest = gate.build_gate_manifest(
        frozen_manifest=_frozen_manifest(),
        validation_config=_validation_config(),
    )

    report = gate.evaluate(_validation(sample_ready=False), gate_manifest=gate_manifest)

    assert report["state"] == "TOO_EARLY"
    assert report["evidence_state"] == "TOO_EARLY"
    assert report["promotion_allowed"] is False
    assert report["performance_gate"]["evaluated"] is False
    assert report["auto_production_promotion"] is False


def test_failed_performance_is_rejected() -> None:
    gate = OOSPromotionGate()
    gate_manifest = gate.build_gate_manifest(
        frozen_manifest=_frozen_manifest(),
        validation_config=_validation_config(),
    )

    report = gate.evaluate(
        _validation(sample_ready=True, performance_pass=False),
        gate_manifest=gate_manifest,
    )

    assert report["evidence_state"] == "EVIDENCE_READY"
    assert report["state"] == "REJECT"
    assert report["promotion_allowed"] is False
    assert "PERFORMANCE_ACCEPTANCE_FAILED" in report["rejection_reasons"]


def test_ambiguous_superiority_continues_accumulating() -> None:
    gate = OOSPromotionGate()
    gate_manifest = gate.build_gate_manifest(
        frozen_manifest=_frozen_manifest(),
        validation_config=_validation_config(),
    )

    report = gate.evaluate(
        _validation(sample_ready=True, superiority_pass=False),
        gate_manifest=gate_manifest,
    )

    assert report["state"] == "CONTINUE_ACCUMULATING"
    assert report["promotion_allowed"] is False
    assert report["superiority_gate"]["evaluated"] is True


def test_accept_only_marks_production_candidate() -> None:
    gate = OOSPromotionGate()
    gate_manifest = gate.build_gate_manifest(
        frozen_manifest=_frozen_manifest(),
        validation_config=_validation_config(),
    )

    report = gate.evaluate(_validation(sample_ready=True), gate_manifest=gate_manifest)

    assert report["state"] == "ACCEPT"
    assert report["promotion_allowed"] is True
    assert report["next_state"] == "PRODUCTION_CANDIDATE"
    assert report["production_execution_mutated"] is False
    assert report["auto_production_promotion"] is False
