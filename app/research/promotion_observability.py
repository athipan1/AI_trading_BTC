from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PromotionGateObservability:
    """Read-only Phase 5.6.4 projection over the Phase 5.6.3 gate artifact."""

    SCHEMA_VERSION = "promotion_gate_observability_schema_v1"

    def __init__(
        self,
        report_path: str | Path,
        *,
        stale_after_seconds: float = 108_000.0,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        self.report_path = Path(report_path)
        self.stale_after_seconds = float(stale_after_seconds)
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    @staticmethod
    def _gate_status(gate: Any) -> str:
        if not isinstance(gate, dict):
            return "UNKNOWN"
        if gate.get("evaluated") is False:
            return "WAITING"
        if gate.get("passed") is True:
            return "PASS"
        if gate.get("passed") is False:
            return "FAIL"
        return "UNKNOWN"

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _base(self, operational_state: str) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.6.4",
            "research_only": True,
            "read_only": True,
            "trade_execution": False,
            "production_mutation": False,
            "operational_state": operational_state,
            "artifact": {
                "path": str(self.report_path),
                "exists": self.report_path.exists(),
                "stale_after_seconds": self.stale_after_seconds,
            },
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a presentation-only snapshot without recomputing any gate decision."""
        if not self.report_path.exists():
            return {
                **self._base("MISSING"),
                "decision": None,
                "evidence": None,
                "gates": None,
                "frozen_contract": None,
                "safety": None,
            }

        stat = self.report_path.stat()
        now = self._now_factory()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        age_seconds = max(0.0, (now - modified_at).total_seconds())

        try:
            raw = json.loads(self.report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {
                **self._base("INVALID"),
                "artifact": {
                    **self._base("INVALID")["artifact"],
                    "modified_at": modified_at.isoformat(),
                    "age_seconds": age_seconds,
                },
                "error": f"{exc.__class__.__name__}: unable to read promotion gate artifact",
                "decision": None,
                "evidence": None,
                "gates": None,
                "frozen_contract": None,
                "safety": None,
            }

        if not isinstance(raw, dict) or raw.get("phase") != "5.6.3":
            return {
                **self._base("INVALID"),
                "artifact": {
                    **self._base("INVALID")["artifact"],
                    "modified_at": modified_at.isoformat(),
                    "age_seconds": age_seconds,
                },
                "error": "promotion gate artifact must be a Phase 5.6.3 JSON object",
                "decision": None,
                "evidence": None,
                "gates": None,
                "frozen_contract": None,
                "safety": None,
            }

        sample_gate = self._safe_dict(raw.get("sample_gate"))
        gate_manifest = self._safe_dict(raw.get("gate_manifest"))
        performance_contract = self._safe_dict(gate_manifest.get("performance_gate"))
        structural_gate = self._safe_dict(raw.get("structural_gate"))
        performance_gate = self._safe_dict(raw.get("performance_gate"))
        superiority_gate = self._safe_dict(raw.get("superiority_gate"))
        safety = self._safe_dict(raw.get("safety"))

        operational_state = "STALE" if age_seconds > self.stale_after_seconds else "HEALTHY"
        return {
            **self._base(operational_state),
            "artifact": {
                **self._base(operational_state)["artifact"],
                "modified_at": modified_at.isoformat(),
                "age_seconds": age_seconds,
            },
            "source": {
                "phase": raw.get("phase"),
                "schema_version": raw.get("schema_version"),
                "method": raw.get("method"),
            },
            "decision": {
                "state": raw.get("state"),
                "evidence_state": raw.get("evidence_state"),
                "promotion_allowed": bool(raw.get("promotion_allowed")),
                "next_state": raw.get("next_state"),
                "rejection_reasons": raw.get("rejection_reasons", []),
            },
            "evidence": {
                "ready": bool(sample_gate.get("ready")),
                "signals": {
                    "current": sample_gate.get("signals"),
                    "required": performance_contract.get("minimum_oos_signals"),
                },
                "policy_selected_trades": {
                    "current": sample_gate.get("policy_selected_trades"),
                    "required": performance_contract.get("minimum_policy_selected_trades"),
                },
                "checks": sample_gate.get("checks", {}),
            },
            "gates": {
                "structural": self._gate_status(structural_gate),
                "performance": self._gate_status(performance_gate),
                "superiority": self._gate_status(superiority_gate),
            },
            "frozen_contract": {
                "model": bool(safety.get("model_frozen")),
                "policy": bool(safety.get("policy_frozen")),
                "threshold": bool(safety.get("threshold_frozen")),
            },
            "safety": {
                "research_only": bool(raw.get("research_only")),
                "oos_retuning_performed": bool(raw.get("oos_retuning_performed")),
                "optimization_performed": bool(raw.get("optimization_performed")),
                "production_position_store_mutated": bool(
                    raw.get("production_position_store_mutated")
                ),
                "production_execution_mutated": bool(raw.get("production_execution_mutated")),
                "auto_production_promotion": bool(raw.get("auto_production_promotion")),
            },
        }
