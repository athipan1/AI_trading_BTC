from __future__ import annotations

from typing import Any


PHASE51_MIN_ADVANCED_COVERAGE_PCT = 95.0
PHASE51_MIN_ADVANCED_ROW_COVERAGE_PCT = 95.0


def evaluate_phase51_runtime_acceptance(
    *,
    diagnostics: dict[str, Any],
    quality: dict[str, Any],
    split: dict[str, Any],
    production_position_store_mutated: bool = False,
) -> dict[str, Any]:
    """Evaluate Phase 5.1 acceptance using read-only research diagnostics."""
    quality_metrics = quality.get("quality", {})
    readiness = quality.get("readiness", {})
    checks = split.get("checks", {})

    advanced_coverage = float(quality_metrics.get("advanced_feature_coverage_pct") or 0.0)
    advanced_row_coverage = float(
        quality_metrics.get("advanced_feature_row_coverage_pct") or 0.0
    )
    temporal_integrity = str(
        (quality_metrics.get("temporal_integrity") or {}).get("status", "FAIL")
    )
    leakage_status = str(
        (quality_metrics.get("leakage_check") or {}).get("status", "FAIL")
    )

    gate = {
        "sample_size_positive": int(quality.get("sample_size") or 0) > 0,
        "duplicate_order_ids_zero": int(diagnostics.get("duplicate_order_ids") or 0) == 0,
        "invalid_rows_zero": int(diagnostics.get("invalid_rows") or 0) == 0,
        "advanced_feature_coverage": (
            advanced_coverage >= PHASE51_MIN_ADVANCED_COVERAGE_PCT
        ),
        "advanced_feature_row_coverage": (
            advanced_row_coverage >= PHASE51_MIN_ADVANCED_ROW_COVERAGE_PCT
        ),
        "temporal_integrity": temporal_integrity == "PASS",
        "leakage": leakage_status == "PASS",
        "dataset_ready": readiness.get("dataset") == "READY",
        "advanced_entry_features_ready": readiness.get("advanced_entry_features") == "READY",
        "chronological_split_ready": split.get("readiness") == "READY",
        "chronological_order": checks.get("chronological_order") == "PASS",
        "split_no_overlap": checks.get("order_id_overlap") == "PASS",
        "production_isolation": production_position_store_mutated is False,
    }
    failed = [name for name, passed in gate.items() if not passed]

    return {
        "phase": "5.1",
        "status": "PASS" if not failed else "FAIL",
        "gate": gate,
        "failed_checks": failed,
        "metrics": {
            "sample_size": int(quality.get("sample_size") or 0),
            "advanced_feature_coverage_pct": advanced_coverage,
            "advanced_feature_row_coverage_pct": advanced_row_coverage,
            "duplicate_order_ids": int(diagnostics.get("duplicate_order_ids") or 0),
            "invalid_rows": int(diagnostics.get("invalid_rows") or 0),
            "temporal_integrity": temporal_integrity,
            "leakage": leakage_status,
            "chronological_split": split.get("readiness"),
            "production_position_store_mutated": production_position_store_mutated,
        },
        "thresholds": {
            "minimum_advanced_feature_coverage_pct": PHASE51_MIN_ADVANCED_COVERAGE_PCT,
            "minimum_advanced_feature_row_coverage_pct": (
                PHASE51_MIN_ADVANCED_ROW_COVERAGE_PCT
            ),
        },
        "read_only": True,
    }
