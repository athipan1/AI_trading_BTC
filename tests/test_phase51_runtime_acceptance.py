from __future__ import annotations

from app.research.runtime_acceptance import evaluate_phase51_runtime_acceptance


def _diagnostics() -> dict[str, object]:
    return {
        "sample_size": 1307,
        "duplicate_order_ids": 0,
        "invalid_rows": 0,
    }


def _quality() -> dict[str, object]:
    return {
        "sample_size": 1307,
        "quality": {
            "advanced_feature_coverage_pct": 100.0,
            "advanced_feature_row_coverage_pct": 100.0,
            "temporal_integrity": {"status": "PASS", "failures": 0},
            "leakage_check": {
                "status": "PASS",
                "forbidden_features": [],
                "unknown_features": [],
            },
        },
        "readiness": {
            "pipeline": "READY",
            "dataset": "READY",
            "training": "READY",
            "advanced_entry_features": "READY",
        },
    }


def _split() -> dict[str, object]:
    return {
        "readiness": "READY",
        "checks": {
            "order_id_overlap": "PASS",
            "chronological_order": "PASS",
        },
    }


def test_phase51_runtime_acceptance_passes_clean_dataset() -> None:
    result = evaluate_phase51_runtime_acceptance(
        diagnostics=_diagnostics(),
        quality=_quality(),
        split=_split(),
        production_position_store_mutated=False,
    )

    assert result["status"] == "PASS"
    assert result["failed_checks"] == []
    assert result["gate"]["production_isolation"] is True


def test_phase51_runtime_acceptance_fails_low_advanced_coverage() -> None:
    quality = _quality()
    quality_metrics = quality["quality"]
    assert isinstance(quality_metrics, dict)
    quality_metrics["advanced_feature_coverage_pct"] = 94.99

    result = evaluate_phase51_runtime_acceptance(
        diagnostics=_diagnostics(),
        quality=quality,
        split=_split(),
    )

    assert result["status"] == "FAIL"
    assert "advanced_feature_coverage" in result["failed_checks"]


def test_phase51_runtime_acceptance_fails_temporal_or_production_mutation() -> None:
    quality = _quality()
    quality_metrics = quality["quality"]
    assert isinstance(quality_metrics, dict)
    quality_metrics["temporal_integrity"] = {"status": "FAIL", "failures": 1}

    result = evaluate_phase51_runtime_acceptance(
        diagnostics=_diagnostics(),
        quality=quality,
        split=_split(),
        production_position_store_mutated=True,
    )

    assert result["status"] == "FAIL"
    assert "temporal_integrity" in result["failed_checks"]
    assert "production_isolation" in result["failed_checks"]
