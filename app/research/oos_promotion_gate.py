from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OOSPromotionGateConfig:
    require_superiority_expectancy: bool = True
    require_superiority_total_r: bool = True
    ambiguous_superiority_action: str = "CONTINUE_ACCUMULATING"
    auto_production_promotion: bool = False


class OOSPromotionGate:
    """Phase 5.6.3 deterministic research-only promotion decision layer."""

    SCHEMA_VERSION = "oos_promotion_gate_schema_v1"
    MANIFEST_SCHEMA_VERSION = "oos_promotion_gate_manifest_v1"

    def __init__(self, *, config: OOSPromotionGateConfig | None = None) -> None:
        self.config = config or OOSPromotionGateConfig()

    @staticmethod
    def _canonical_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def build_gate_manifest(
        self,
        *,
        frozen_manifest: dict[str, Any],
        validation_config: dict[str, Any],
    ) -> dict[str, Any]:
        required_frozen_fields = (
            "manifest_hash",
            "policy_hash",
            "model_fingerprint",
            "discovery_cutoff",
        )
        missing = [field for field in required_frozen_fields if not frozen_manifest.get(field)]
        if missing:
            raise ValueError(f"Phase 5.6.3 frozen manifest missing required fields: {missing}")

        required_validation_fields = (
            "minimum_oos_signals",
            "minimum_policy_selected_trades",
            "minimum_policy_profit_factor",
            "require_positive_policy_expectancy",
            "require_policy_drawdown_not_worse_than_global_ml",
        )
        missing_validation = [
            field for field in required_validation_fields if field not in validation_config
        ]
        if missing_validation:
            raise ValueError(
                "Phase 5.6.3 validation config missing frozen gate fields: "
                f"{missing_validation}"
            )

        body = {
            "schema_version": self.MANIFEST_SCHEMA_VERSION,
            "phase": "5.6.3",
            "research_only": True,
            "source_frozen_contract": {
                field: frozen_manifest[field] for field in required_frozen_fields
            },
            "performance_gate": {
                field: validation_config[field] for field in required_validation_fields
            },
            "superiority_gate": {
                "require_superiority_expectancy": self.config.require_superiority_expectancy,
                "require_superiority_total_r": self.config.require_superiority_total_r,
            },
            "decision_policy": {
                "ambiguous_superiority_action": self.config.ambiguous_superiority_action,
                "auto_production_promotion": self.config.auto_production_promotion,
            },
            "oos_retuning_allowed": False,
            "optimization_allowed": False,
            "production_execution_mutation_allowed": False,
        }
        return {**body, "gate_manifest_hash": self._canonical_hash(body)}

    def verify_gate_manifest(
        self,
        gate_manifest: dict[str, Any],
        *,
        frozen_manifest: dict[str, Any],
        validation_config: dict[str, Any],
    ) -> None:
        expected = self.build_gate_manifest(
            frozen_manifest=frozen_manifest,
            validation_config=validation_config,
        )
        if gate_manifest != expected:
            raise ValueError(
                "Phase 5.6.3 promotion gate manifest differs from the frozen contract"
            )

    def load_or_freeze_gate_manifest(
        self,
        path: str | Path,
        *,
        frozen_manifest: dict[str, Any],
        validation_config: dict[str, Any],
    ) -> dict[str, Any]:
        manifest_path = Path(path)
        expected = self.build_gate_manifest(
            frozen_manifest=frozen_manifest,
            validation_config=validation_config,
        )
        if manifest_path.exists():
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                raise ValueError("Phase 5.6.3 gate manifest must contain a JSON object")
            self.verify_gate_manifest(
                current,
                frozen_manifest=frozen_manifest,
                validation_config=validation_config,
            )
            return current

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(manifest_path)
        return expected

    def evaluate(
        self,
        validation: dict[str, Any],
        *,
        gate_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = validation.get("evidence_acceptance", {})
        performance = validation.get("performance_acceptance", {})
        superiority = validation.get("superiority", {})
        comparison = validation.get("comparison", {})
        structural = validation.get("structural_acceptance", {})
        oos = validation.get("oos", {})

        sample_ready = bool(evidence) and all(bool(value) for value in evidence.values())
        structural_pass = bool(structural) and all(bool(value) for value in structural.values())
        performance_pass = bool(performance) and all(bool(value) for value in performance.values())

        superiority_expectancy = bool(superiority.get("policy_expectancy_ge_global_ml"))
        superiority_total_r = bool(superiority.get("policy_total_r_ge_global_ml"))
        superiority_pass = (
            (not self.config.require_superiority_expectancy or superiority_expectancy)
            and (not self.config.require_superiority_total_r or superiority_total_r)
        )

        evidence_state = "EVIDENCE_READY" if sample_ready else "TOO_EARLY"
        rejection_reasons: list[str] = []

        if not sample_ready:
            decision = "TOO_EARLY"
        elif not structural_pass:
            decision = "REJECT"
            rejection_reasons.append("STRUCTURAL_ACCEPTANCE_FAILED")
        elif not performance_pass:
            decision = "REJECT"
            rejection_reasons.append("PERFORMANCE_ACCEPTANCE_FAILED")
        elif not superiority_pass:
            decision = self.config.ambiguous_superiority_action
        else:
            decision = "ACCEPT"

        promotion_allowed = decision == "ACCEPT"
        next_state = "PRODUCTION_CANDIDATE" if promotion_allowed else None

        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.6.3",
            "research_only": True,
            "production_position_store_mutated": False,
            "production_execution_mutated": False,
            "optimization_performed": False,
            "oos_retuning_performed": False,
            "method": "deterministic_frozen_oos_evidence_promotion_gate",
            "state": decision,
            "evidence_state": evidence_state,
            "promotion_allowed": promotion_allowed,
            "next_state": next_state,
            "auto_production_promotion": False,
            "gate_manifest": gate_manifest,
            "sample_gate": {
                "ready": sample_ready,
                "checks": evidence,
                "signals": oos.get("signals"),
                "policy_selected_trades": (
                    comparison.get("frozen_regime_policy", {}).get("trade_count")
                    if isinstance(comparison.get("frozen_regime_policy"), dict)
                    else None
                ),
            },
            "structural_gate": {
                "passed": structural_pass,
                "checks": structural,
            },
            "performance_gate": {
                "evaluated": sample_ready,
                "passed": performance_pass if sample_ready else False,
                "checks": performance,
                "policy_metrics": comparison.get("frozen_regime_policy"),
            },
            "superiority_gate": {
                "evaluated": sample_ready and structural_pass and performance_pass,
                "passed": superiority_pass if sample_ready else False,
                "checks": superiority,
                "global_ml_metrics": comparison.get("global_ml"),
            },
            "rejection_reasons": rejection_reasons,
            "safety": {
                "model_frozen": bool(structural.get("model_frozen")),
                "policy_frozen": bool(structural.get("policy_frozen")),
                "threshold_frozen": bool(structural.get("threshold_frozen")),
                "fresh_oos": bool(structural.get("fresh_oos")),
                "chronological_integrity": bool(structural.get("chronological_integrity")),
                "feature_leakage_free": bool(structural.get("feature_leakage")),
                "production_isolation": bool(structural.get("production_isolation")),
            },
            "config": asdict(self.config),
        }
