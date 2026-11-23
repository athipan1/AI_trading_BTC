"""Read-only Phase 5.7 diagnosis of existing frozen OOS promotion evidence.

This projection never fits models, changes thresholds, or touches execution state.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class OOSPromotionDiagnostics:
    """Explain which frozen checks block promotion without re-evaluating the gate."""

    SCHEMA_VERSION = "oos_promotion_diagnostics_schema_v1"
    PROMOTION_SCHEMA_VERSION = "oos_promotion_gate_schema_v1"
    INTEGRITY_SCHEMA_VERSION = "evidence_integrity_schema_v1"
    MILESTONE_SCHEMA_VERSION = "oos_milestone_evidence_history_v1"
    _PIN_FIELDS = ("manifest_hash", "policy_hash", "model_fingerprint", "discovery_cutoff")

    @staticmethod
    def _object(value: Any, name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be a JSON object")
        return value

    @staticmethod
    def _finite(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _check_statuses(
        cls,
        checks: dict[str, Any],
        *,
        evaluated: bool,
        expected_false: frozenset[str] = frozenset(),
    ) -> dict[str, str]:
        if not evaluated:
            return {name: "NOT_EVALUATED" for name in sorted(checks)}
        return {
            name: (
                "PASS"
                if isinstance(value, bool) and value is (name not in expected_false)
                else "FAIL"
                if isinstance(value, bool)
                else "UNKNOWN"
            )
            for name, value in sorted(checks.items())
        }

    @classmethod
    def _checks(
        cls, gate: dict[str, Any], *, expected_false: frozenset[str] = frozenset()
    ) -> dict[str, Any]:
        raw = cls._object(gate.get("checks"), "gate checks")
        evaluated = gate.get("evaluated", True) is True
        statuses = cls._check_statuses(raw, evaluated=evaluated, expected_false=expected_false)
        return {
            "evaluated": evaluated,
            "reported_passed": gate.get("passed") is True,
            "statuses": statuses,
            "failed": [name for name, status in statuses.items() if status == "FAIL"],
            "unknown": [name for name, status in statuses.items() if status == "UNKNOWN"],
        }

    @classmethod
    def _metric_comparison(
        cls, policy: dict[str, Any], global_ml: dict[str, Any], contract: dict[str, Any]
    ) -> dict[str, Any]:
        expected = cls._finite(contract.get("minimum_policy_profit_factor"))
        pf = cls._finite(policy.get("profit_factor"))
        expectancy = cls._finite(policy.get("expectancy_r"))
        dd = cls._finite(policy.get("max_drawdown_r"))
        global_dd = cls._finite(global_ml.get("max_drawdown_r"))
        global_expectancy = cls._finite(global_ml.get("expectancy_r"))
        total = cls._finite(policy.get("total_realized_r"))
        global_total = cls._finite(global_ml.get("total_realized_r"))
        return {
            "policy": {
                "trade_count": policy.get("trade_count"),
                "expectancy_r": expectancy,
                "profit_factor": pf,
                "max_drawdown_r": dd,
                "total_realized_r": total,
                "win_rate_pct": cls._finite(policy.get("win_rate_pct")),
            },
            "global_ml": {
                "trade_count": global_ml.get("trade_count"),
                "expectancy_r": global_expectancy,
                "max_drawdown_r": global_dd,
                "total_realized_r": global_total,
            },
            "frozen_requirements": {
                "minimum_policy_profit_factor": expected,
                "require_positive_policy_expectancy": contract.get(
                    "require_positive_policy_expectancy"
                ),
                "require_policy_drawdown_not_worse_than_global_ml": contract.get(
                    "require_policy_drawdown_not_worse_than_global_ml"
                ),
            },
            "observed_deltas_not_new_gates": {
                "profit_factor_minus_required": (
                    pf - expected if pf is not None and expected is not None else None
                ),
                "expectancy_r_minus_zero": expectancy,
                "drawdown_r_minus_global_ml": (
                    dd - global_dd if dd is not None and global_dd is not None else None
                ),
                "expectancy_r_minus_global_ml": (
                    expectancy - global_expectancy
                    if expectancy is not None and global_expectancy is not None
                    else None
                ),
                "total_r_minus_global_ml": (
                    total - global_total if total is not None and global_total is not None else None
                ),
            },
        }

    @classmethod
    def _milestones(cls, history: dict[str, Any], promotion: dict[str, Any]) -> list[dict[str, Any]]:
        # Reuse the canonical Phase 5.6.8 hash-chain and candidate-pin verifier.
        from app.research.oos_milestones import OOSMilestoneEvidenceHistory

        recorder = OOSMilestoneEvidenceHistory()
        pin = recorder._candidate_pin(promotion)
        recorder._verify_history(history, candidate_pin=pin)
        result: list[dict[str, Any]] = []
        for entry in history["milestones"]:
            metrics = cls._object(
                cls._object(entry.get("performance_gate"), "milestone performance").get(
                    "policy_metrics"
                ),
                "milestone policy metrics",
            )
            state = cls._object(entry.get("promotion"), "milestone promotion").get("state")
            result.append(
                {
                    "milestone_signals": entry["milestone_signals"],
                    "observed_signals": entry["observed_signals"],
                    "capture_mode": entry["capture_mode"],
                    "promotion_state": state,
                    "expectancy_r": cls._finite(metrics.get("expectancy_r")),
                    "profit_factor": cls._finite(metrics.get("profit_factor")),
                    "max_drawdown_r": cls._finite(metrics.get("max_drawdown_r")),
                    "snapshot_hash": entry["snapshot_hash"],
                }
            )
        return result

    @classmethod
    def analyze(
        cls,
        promotion: dict[str, Any],
        *,
        integrity: dict[str, Any] | None = None,
        milestone_history: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Produce deterministic, research-only diagnostics from immutable artifacts."""
        cls._object(promotion, "promotion")
        if (
            promotion.get("schema_version") != cls.PROMOTION_SCHEMA_VERSION
            or promotion.get("phase") != "5.6.3"
            or promotion.get("research_only") is not True
        ):
            raise ValueError("expected research-only Phase 5.6.3 promotion report")
        for flag in (
            "production_position_store_mutated",
            "production_execution_mutated",
            "optimization_performed",
            "oos_retuning_performed",
            "auto_production_promotion",
        ):
            if promotion.get(flag) is not False:
                raise ValueError(f"unsafe or missing promotion safety flag: {flag}")

        gate_manifest = cls._object(promotion.get("gate_manifest"), "gate_manifest")
        if gate_manifest.get("schema_version") != "oos_promotion_gate_manifest_v1":
            raise ValueError("unsupported frozen gate manifest schema")
        saved_hash = gate_manifest.get("gate_manifest_hash")
        computed_hash = cls._hash({k: v for k, v in gate_manifest.items() if k != "gate_manifest_hash"})
        if saved_hash != computed_hash:
            raise ValueError("frozen gate manifest hash mismatch")
        frozen_pin = cls._object(gate_manifest.get("source_frozen_contract"), "frozen pin")
        if any(not frozen_pin.get(key) for key in cls._PIN_FIELDS):
            raise ValueError("frozen candidate pin is incomplete")
        contract = cls._object(gate_manifest.get("performance_gate"), "performance contract")
        sample = cls._object(promotion.get("sample_gate"), "sample_gate")
        structural = cls._checks(
            cls._object(promotion.get("structural_gate"), "structural_gate"),
            expected_false=frozenset({"oos_retuning"}),
        )
        performance_gate = cls._object(promotion.get("performance_gate"), "performance_gate")
        performance = cls._checks(performance_gate)
        superiority_gate = cls._object(promotion.get("superiority_gate"), "superiority_gate")
        superiority = cls._checks(superiority_gate)
        evidence = {
            "signals": sample.get("signals"),
            "minimum_signals": contract.get("minimum_oos_signals"),
            "policy_selected_trades": sample.get("policy_selected_trades"),
            "minimum_policy_selected_trades": contract.get("minimum_policy_selected_trades"),
            "ready": sample.get("ready") is True,
            "checks": cls._check_statuses(cls._object(sample.get("checks"), "sample checks"), evaluated=True),
        }
        policy_metrics = cls._object(performance_gate.get("policy_metrics"), "policy metrics")
        global_metrics = cls._object(superiority_gate.get("global_ml_metrics"), "global ML metrics")
        blockers = {
            "evidence": [key for key, status in evidence["checks"].items() if status != "PASS"],
            "structural": structural["failed"] + structural["unknown"],
            "performance": performance["failed"] + performance["unknown"],
            "superiority": superiority["failed"] + superiority["unknown"],
        }
        evidence_trust = "NOT_VERIFIED"
        if integrity is not None:
            cls._object(integrity, "integrity")
            if integrity.get("schema_version") != cls.INTEGRITY_SCHEMA_VERSION:
                raise ValueError("unsupported evidence integrity schema")
            evidence_trust = (
                "VERIFIED_HEALTHY"
                if integrity.get("integrity_ok") is True
                and integrity.get("state") == "PASS"
                and integrity.get("operational_state") == "HEALTHY"
                else "BLOCKED_INTEGRITY"
            )
        milestones = cls._milestones(milestone_history, promotion) if milestone_history is not None else []
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "phase": "5.7.1",
            "research_only": True,
            "read_only": True,
            "trade_execution": False,
            "production_mutation": False,
            "optimization_performed": False,
            "oos_retuning_performed": False,
            "auto_production_promotion": False,
            "promotion_state_unchanged": promotion.get("state"),
            "promotion_allowed_unchanged": promotion.get("promotion_allowed") is True,
            "evidence_trust": evidence_trust,
            "frozen_pin": {key: frozen_pin[key] for key in cls._PIN_FIELDS},
            "evidence": evidence,
            "gate_diagnostics": {
                "structural": structural,
                "performance": performance,
                "superiority": superiority,
            },
            "blocking_checks": blockers,
            "reported_rejection_reasons": list(promotion.get("rejection_reasons") or []),
            "metric_comparison": cls._metric_comparison(policy_metrics, global_metrics, contract),
            "verified_milestones": milestones,
            "candidate_v2_research_plan": {
                "allowed_data": "discovery_and_separate_new_training_data_only",
                "forbidden": "retune_frozen_v1_against_seen_oos",
                "steps": [
                    "attribute failures by strategy, side and regime in discovery data",
                    "specify candidate V2 features and parameters before looking at its test period",
                    "walk-forward validation with fees and slippage",
                    "freeze V2 then evaluate on untouched later OOS and compare against V1",
                ],
                "production_activation": "NOT_AUTHORIZED",
            },
        }