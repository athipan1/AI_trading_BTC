from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.research.promotion_observability import PromotionGateObservability


class ResearchOperationsProjection:
    """Phase 5.6.7 read-only aggregation of frozen Research/OOS operations state."""

    SCHEMA_VERSION = "research_operations_schema_v1"
    INTEGRITY_SCHEMA_VERSION = "evidence_integrity_schema_v1"
    CHECKPOINT_SCHEMA_VERSION = "forward_oos_checkpoint_schema_v1"
    SCHEDULER_SCHEMA_VERSION = "phase562_daily_scheduler_state_v1"

    def __init__(
        self,
        *,
        promotion_observability: PromotionGateObservability,
        integrity_report_path: str | Path,
        checkpoint_path: str | Path,
        scheduler_state_path: str | Path,
    ) -> None:
        self.promotion_observability = promotion_observability
        self.integrity_report_path = Path(integrity_report_path)
        self.checkpoint_path = Path(checkpoint_path)
        self.scheduler_state_path = Path(scheduler_state_path)

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _read_json_object(
        path: Path,
        *,
        expected_phase: str | None = None,
        expected_schema: str | None = None,
    ) -> tuple[dict[str, Any] | None, str, str | None]:
        if not path.exists():
            return None, "MISSING", None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return None, "INVALID", f"{exc.__class__.__name__}: unable to read artifact"
        if not isinstance(payload, dict):
            return None, "INVALID", "artifact must contain a JSON object"
        if expected_phase is not None and payload.get("phase") != expected_phase:
            return None, "INVALID", f"artifact must be Phase {expected_phase}"
        if expected_schema is not None and payload.get("schema_version") != expected_schema:
            return None, "INVALID", f"unsupported artifact schema: {payload.get('schema_version')}"
        return payload, "HEALTHY", None

    @staticmethod
    def _artifact(path: Path, state: str, error: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path": str(path),
            "exists": path.exists(),
            "operational_state": state,
        }
        if error is not None:
            result["error"] = error
        return result

    def _integrity_snapshot(self) -> dict[str, Any]:
        payload, read_state, error = self._read_json_object(
            self.integrity_report_path,
            expected_phase="5.6.5",
            expected_schema=self.INTEGRITY_SCHEMA_VERSION,
        )
        if payload is None:
            return {
                "state": "UNKNOWN",
                "operational_state": read_state,
                "integrity_ok": None,
                "checks": None,
                "violations": None,
                "evidence": None,
                "artifact": self._artifact(self.integrity_report_path, read_state, error),
            }
        operational_state = str(payload.get("operational_state") or "UNKNOWN")
        return {
            "state": str(payload.get("state") or "UNKNOWN"),
            "operational_state": operational_state,
            "integrity_ok": bool(payload.get("integrity_ok")),
            "checks": self._safe_dict(payload.get("checks")),
            "violations": self._safe_dict(payload.get("violations")),
            "evidence": self._safe_dict(payload.get("evidence")),
            "artifact": self._artifact(self.integrity_report_path, operational_state),
        }

    def _checkpoint_snapshot(self) -> dict[str, Any]:
        payload, read_state, error = self._read_json_object(
            self.checkpoint_path,
            expected_phase="5.6.2",
            expected_schema=self.CHECKPOINT_SCHEMA_VERSION,
        )
        if payload is None:
            return {
                "operational_state": read_state,
                "run_count": None,
                "last_processed_until": None,
                "last_oos_trade_count": None,
                "last_evidence_stage": None,
                "last_state": None,
                "artifact": self._artifact(self.checkpoint_path, read_state, error),
            }
        return {
            "operational_state": "HEALTHY",
            "run_count": payload.get("run_count"),
            "last_processed_until": payload.get("last_processed_until"),
            "last_oos_trade_count": payload.get("last_oos_trade_count"),
            "last_evidence_stage": payload.get("last_evidence_stage"),
            "last_state": payload.get("last_state"),
            "artifact": self._artifact(self.checkpoint_path, "HEALTHY"),
        }

    def _scheduler_snapshot(self) -> dict[str, Any]:
        payload, read_state, error = self._read_json_object(
            self.scheduler_state_path,
            expected_schema=self.SCHEDULER_SCHEMA_VERSION,
        )
        if payload is None:
            return {
                "operational_state": read_state,
                "last_result": None,
                "last_attempt_at": None,
                "last_run_local_date": None,
                "timezone": None,
                "scheduled_local_time": None,
                "artifact": self._artifact(self.scheduler_state_path, read_state, error),
            }

        last_result = str(payload.get("last_result") or "UNKNOWN")
        return_code = payload.get("last_return_code")
        failed = last_result == "FAILED" or (
            isinstance(return_code, int) and not isinstance(return_code, bool) and return_code != 0
        )
        operational_state = "FAILED" if failed else "HEALTHY" if last_result == "SUCCESS" else "UNKNOWN"
        return {
            "operational_state": operational_state,
            "last_result": last_result,
            "last_attempt_at": payload.get("last_attempt_at"),
            "last_run_local_date": payload.get("last_run_local_date"),
            "timezone": payload.get("timezone"),
            "scheduled_local_time": payload.get("scheduled_local_time"),
            "artifact": self._artifact(self.scheduler_state_path, operational_state),
        }

    @staticmethod
    def _overall_state(states: list[str]) -> str:
        if "INVALID" in states:
            return "INVALID"
        if any(state in {"FAIL", "FAILED"} for state in states):
            return "DEGRADED"
        if "MISSING" in states:
            return "MISSING"
        if "STALE" in states:
            return "STALE"
        if "UNKNOWN" in states:
            return "UNKNOWN"
        return "HEALTHY"

    def snapshot(self) -> dict[str, Any]:
        """Combine existing authoritative artifacts without recomputing or mutating research."""
        promotion = self.promotion_observability.snapshot()
        evidence = self._safe_dict(promotion.get("evidence"))
        decision = self._safe_dict(promotion.get("decision"))
        integrity = self._integrity_snapshot()
        checkpoint = self._checkpoint_snapshot()
        scheduler = self._scheduler_snapshot()

        signals = self._safe_dict(evidence.get("signals"))
        selected = self._safe_dict(evidence.get("policy_selected_trades"))
        promotion_state = str(promotion.get("operational_state") or "UNKNOWN")
        integrity_health = str(integrity.get("operational_state") or "UNKNOWN")
        if integrity.get("state") == "FAIL":
            integrity_health = "FAIL"

        operational_state = self._overall_state(
            [
                promotion_state,
                integrity_health,
                str(checkpoint.get("operational_state") or "UNKNOWN"),
                str(scheduler.get("operational_state") or "UNKNOWN"),
            ]
        )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.6.7",
            "research_only": True,
            "read_only": True,
            "trade_execution": False,
            "production_mutation": False,
            "operational_state": operational_state,
            "forward_oos": {
                "signals": {
                    "current": signals.get("current"),
                    "required": signals.get("required"),
                },
                "policy_selected_trades": {
                    "current": selected.get("current"),
                    "required": selected.get("required"),
                },
                "evidence_ready": evidence.get("ready"),
                "run_count": checkpoint.get("run_count"),
                "last_processed_until": checkpoint.get("last_processed_until"),
                "last_oos_trade_count": checkpoint.get("last_oos_trade_count"),
                "last_evidence_stage": checkpoint.get("last_evidence_stage"),
                "last_state": checkpoint.get("last_state"),
                "operational_state": checkpoint.get("operational_state"),
            },
            "integrity": integrity,
            "promotion": {
                "state": decision.get("state"),
                "evidence_state": decision.get("evidence_state"),
                "promotion_allowed": bool(decision.get("promotion_allowed")),
                "next_state": decision.get("next_state"),
                "rejection_reasons": decision.get("rejection_reasons", []),
                "gates": promotion.get("gates"),
                "operational_state": promotion_state,
            },
            "frozen_contract": promotion.get("frozen_contract"),
            "scheduler": scheduler,
            "safety": {
                "research_only": True,
                "read_only": True,
                "trade_execution": False,
                "production_position_store_mutated": False,
                "production_execution_mutated": False,
                "optimization_performed": False,
                "oos_retuning_performed": False,
                "auto_production_promotion": False,
            },
        }
