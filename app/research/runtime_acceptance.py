PHASE51_MIN_ADVANCED_COVERAGE_PCT = 95.0
PHASE51_MIN_ADVANCED_ROW_COVERAGE_PCT = 95.0


def evaluate_phase51_runtime_acceptance(
    *,
    diagnostics: dict[str, object],
    quality: dict[str, object],
    split: dict[str, object],
    production_position_store_mutated: bool = False,
) -> dict[str, object]:
    """Evaluate Phase 5.1 acceptance using read-only research diagnostics."""
    quality_metrics = quality.get("quality", {})
    readiness = quality.get("readiness", {})
    checks = split.get("checks", {})

    quality_metrics_map = quality_metrics if isinstance(quality_metrics, dict) else {}
    readiness_map = readiness if isinstance(readiness, dict) else {}
    checks_map = checks if isinstance(checks, dict) else {}

    temporal = quality_metrics_map.get("temporal_integrity") or {}
    leakage = quality_metrics_map.get("leakage_check") or {}
    temporal_map = temporal if isinstance(temporal, dict) else {}
    leakage_map = leakage if isinstance(leakage, dict) else {}

    advanced_coverage = float(quality_metrics_map.get("advanced_feature_coverage_pct") or 0.0)
    advanced_row_coverage = float(
        quality_metrics_map.get("advanced_feature_row_coverage_pct") or 0.0
    )
    temporal_integrity = str(temporal_map.get("status", "FAIL"))
    leakage_status = str(leakage_map.get("status", "FAIL"))

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
        "dataset_ready": readiness_map.get("dataset") == "READY",
        "advanced_entry_features_ready": readiness_map.get("advanced_entry_features") == "READY",
        "chronological_split_ready": split.get("readiness") == "READY",
        "chronological_order": checks_map.get("chronological_order") == "PASS",
        "split_no_overlap": checks_map.get("order_id_overlap") == "PASS",
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
