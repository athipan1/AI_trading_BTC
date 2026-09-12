from __future__ import annotations

import numpy as np
import pytest

from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.frozen_oos_validation import FrozenOOSValidationResearch


def test_manifest_hash_is_canonical() -> None:
    research = FrozenOOSValidationResearch()
    left = {"b": 2, "a": {"y": 1, "x": 0}}
    right = {"a": {"x": 0, "y": 1}, "b": 2}

    assert research._canonical_hash(left) == research._canonical_hash(right)


def test_frozen_policy_actions_are_conservative() -> None:
    action = FrozenOOSValidationResearch._policy_action

    assert action("ROBUST") == "ML_FILTER"
    assert action("PROMISING") == "ML_FILTER"
    assert action("FAILURE") == "RULE_BASED"
    assert action("UNSTABLE") == "RULE_BASED"
    assert action("INSUFFICIENT") == "RULE_BASED"
    assert action(None) == "GLOBAL_ML_FALLBACK"


def test_oos_metrics_include_profit_factor_and_drawdown() -> None:
    realized = np.asarray([1.0, -0.5, 2.0, -1.0], dtype=float)
    selected = np.asarray([True, True, True, True], dtype=bool)

    metrics = FrozenOOSValidationResearch._metrics(realized, selected)

    assert metrics["trade_count"] == 4
    assert metrics["expectancy_r"] == pytest.approx(0.375)
    assert metrics["profit_factor"] == pytest.approx(2.0)
    assert metrics["max_drawdown_r"] == pytest.approx(1.0)


def test_validate_rejects_oos_that_overlaps_discovery(monkeypatch) -> None:
    research = FrozenOOSValidationResearch()
    body = {
        "schema_version": research.MANIFEST_SCHEMA_VERSION,
        "phase": "5.6",
        "research_only": True,
        "discovery_cutoff": "2026-09-01T00:00:00+00:00",
        "source_phase": {
            "phase": "5.5",
            "schema_version": "regime_robustness_schema_v1",
            "acceptance_status": "PASS",
            "phase54_acceptance_status": "FAIL",
        },
        "model_contract": {"model": "logistic_regression", "threshold": 0.55},
        "model_fingerprint": "model",
        "policy": {},
        "policy_hash": research._canonical_hash({}),
        "default_policy_action": "GLOBAL_ML_FALLBACK",
        "oos_retuning_allowed": False,
        "production_position_store_mutated": False,
    }
    manifest = {**body, "manifest_hash": research._canonical_hash(body)}

    def fake_quality(cls, positions, **kwargs):
        return {"quality": {"leakage_check": {"status": "PASS"}}}

    def fake_build(cls, positions, **kwargs):
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "rows": [
                {
                    "order_id": "overlap",
                    "feature_available_at": "2026-09-01T00:00:00+00:00",
                    "features": {},
                    "targets": {"realized_r": 1.0},
                }
            ],
        }

    monkeypatch.setattr(
        ResearchFeatureDatasetProjection,
        "quality",
        classmethod(fake_quality),
    )
    monkeypatch.setattr(
        ResearchFeatureDatasetProjection,
        "build",
        classmethod(fake_build),
    )

    with pytest.raises(ValueError, match="strictly after discovery cutoff"):
        research.validate([], [], manifest=manifest)
