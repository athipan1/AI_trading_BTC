from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class OOSMilestoneEvidenceHistory:
    """Phase 5.6.8 tamper-evident, append-only OOS milestone snapshots."""

    SCHEMA_VERSION = "oos_milestone_evidence_history_v1"
    PROMOTION_SCHEMA_VERSION = "oos_promotion_gate_schema_v1"
    INTEGRITY_SCHEMA_VERSION = "evidence_integrity_schema_v1"
    CHECKPOINT_SCHEMA_VERSION = "forward_oos_checkpoint_schema_v1"
    MILESTONES = (20, 50, 100)
    _PIN_FIELDS = (
        "manifest_hash",
        "policy_hash",
        "model_fingerprint",
        "discovery_cutoff",
    )

    def __init__(
        self,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.now_factory = now_factory or (lambda: datetime.now(UTC))

    @staticmethod
    def _canonical_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _read_json_object(
        path: str | Path,
        *,
        expected_schema: str,
        expected_phase: str | None = None,
    ) -> dict[str, Any]:
        artifact = Path(path)
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{artifact} must contain a JSON object")
        if payload.get("schema_version") != expected_schema:
            raise ValueError(f"{artifact} has unsupported schema {payload.get('schema_version')}")
        if expected_phase is not None and payload.get("phase") != expected_phase:
            raise ValueError(f"{artifact} must be Phase {expected_phase}")
        return payload

    @classmethod
    def _candidate_pin(cls, promotion: dict[str, Any]) -> dict[str, Any]:
        gate_manifest = promotion.get("gate_manifest")
        if not isinstance(gate_manifest, dict):
            raise ValueError("promotion report is missing gate_manifest")
        frozen = gate_manifest.get("source_frozen_contract")
        if not isinstance(frozen, dict):
            raise ValueError("promotion report is missing source_frozen_contract")
        missing = [field for field in cls._PIN_FIELDS if not frozen.get(field)]
        if missing:
            raise ValueError(f"promotion frozen contract is missing fields: {missing}")
        gate_manifest_hash = gate_manifest.get("gate_manifest_hash")
        if not gate_manifest_hash:
            raise ValueError("promotion gate manifest hash is missing")
        return {
            "gate_manifest_hash": gate_manifest_hash,
            **{field: frozen[field] for field in cls._PIN_FIELDS},
        }

    @staticmethod
    def _int_counter(value: Any, *, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
        return value

    @staticmethod
    def _metric_subset(metrics: Any) -> dict[str, Any]:
        if not isinstance(metrics, dict):
            return {}
        fields = (
            "available_signals",
            "expectancy_r",
            "max_drawdown_r",
            "profit_factor",
            "selection_rate_pct",
            "total_realized_r",
            "trade_count",
            "win_rate_pct",
        )
        return {field: metrics.get(field) for field in fields if field in metrics}

    def _empty_history(self, candidate_pin: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.6.8",
            "research_only": True,
            "append_only": True,
            "trade_execution": False,
            "production_mutation": False,
            "milestone_targets": list(self.MILESTONES),
            "candidate_pin": candidate_pin,
            "milestones": [],
            "safety": {
                "production_position_store_mutated": False,
                "production_execution_mutated": False,
                "optimization_performed": False,
                "oos_retuning_performed": False,
                "auto_production_promotion": False,
            },
        }

    def _verify_history(
        self,
        history: dict[str, Any],
        *,
        candidate_pin: dict[str, Any],
    ) -> None:
        if history.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported Phase 5.6.8 milestone history schema")
        if history.get("phase") != "5.6.8":
            raise ValueError("milestone history must be Phase 5.6.8")
        if history.get("candidate_pin") != candidate_pin:
            raise ValueError("milestone history candidate pin differs from frozen candidate")
        if history.get("milestone_targets") != list(self.MILESTONES):
            raise ValueError("milestone targets differ from the frozen Phase 5.6.8 contract")
        entries = history.get("milestones")
        if not isinstance(entries, list):
            raise ValueError("milestone history must contain a milestone list")

        seen: set[int] = set()
        previous_hash: str | None = None
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("milestone entry must be a JSON object")
            milestone = self._int_counter(
                entry.get("milestone_signals"),
                field="milestone_signals",
            )
            if milestone not in self.MILESTONES or milestone in seen:
                raise ValueError("milestone history contains an invalid or duplicate milestone")
            if entry.get("previous_snapshot_hash") != previous_hash:
                raise ValueError("milestone history hash chain is invalid")
            snapshot_hash = entry.get("snapshot_hash")
            body = {key: value for key, value in entry.items() if key != "snapshot_hash"}
            if snapshot_hash != self._canonical_hash(body):
                raise ValueError("milestone history snapshot hash is invalid")
            seen.add(milestone)
            previous_hash = str(snapshot_hash)

    def _load_history(
        self,
        path: Path,
        *,
        candidate_pin: dict[str, Any],
    ) -> dict[str, Any]:
        if not path.exists():
            return self._empty_history(candidate_pin)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("milestone history must contain a JSON object")
        self._verify_history(payload, candidate_pin=candidate_pin)
        return payload

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _build_entry(
        self,
        *,
        milestone: int,
        observed_signals: int,
        promotion: dict[str, Any],
        integrity: dict[str, Any],
        checkpoint: dict[str, Any],
        previous_hash: str | None,
    ) -> dict[str, Any]:
        sample = promotion.get("sample_gate")
        performance = promotion.get("performance_gate")
        superiority = promotion.get("superiority_gate")
        structural = promotion.get("structural_gate")
        if not isinstance(sample, dict):
            raise ValueError("promotion report is missing sample_gate")
        if not isinstance(performance, dict):
            raise ValueError("promotion report is missing performance_gate")
        if not isinstance(superiority, dict):
            raise ValueError("promotion report is missing superiority_gate")
        if not isinstance(structural, dict):
            raise ValueError("promotion report is missing structural_gate")

        policy_selected = self._int_counter(
            sample.get("policy_selected_trades"),
            field="policy_selected_trades",
        )
        body: dict[str, Any] = {
            "milestone_signals": milestone,
            "observed_signals": observed_signals,
            "capture_mode": (
                "EXACT"
                if observed_signals == milestone
                else "BACKFILL_AT_OR_AFTER_MILESTONE"
            ),
            "recorded_at": self.now_factory().astimezone(UTC).isoformat(),
            "last_processed_until": checkpoint.get("last_processed_until"),
            "run_count": checkpoint.get("run_count"),
            "evidence_stage": checkpoint.get("last_evidence_stage"),
            "integrity": {
                "state": integrity.get("state"),
                "operational_state": integrity.get("operational_state"),
                "integrity_ok": integrity.get("integrity_ok"),
            },
            "sample": {
                "signals": observed_signals,
                "policy_selected_trades": policy_selected,
                "ready": bool(sample.get("ready")),
            },
            "promotion": {
                "state": promotion.get("state"),
                "evidence_state": promotion.get("evidence_state"),
                "promotion_allowed": bool(promotion.get("promotion_allowed")),
                "next_state": promotion.get("next_state"),
                "rejection_reasons": list(promotion.get("rejection_reasons") or []),
            },
            "structural_gate": {
                "passed": bool(structural.get("passed")),
                "checks": structural.get("checks"),
            },
            "performance_gate": {
                "evaluated": bool(performance.get("evaluated")),
                "passed": bool(performance.get("passed")),
                "checks": performance.get("checks"),
                "policy_metrics": self._metric_subset(performance.get("policy_metrics")),
            },
            "superiority_gate": {
                "evaluated": bool(superiority.get("evaluated")),
                "passed": bool(superiority.get("passed")),
                "checks": superiority.get("checks"),
                "global_ml_metrics": self._metric_subset(superiority.get("global_ml_metrics")),
            },
            "previous_snapshot_hash": previous_hash,
        }
        return {**body, "snapshot_hash": self._canonical_hash(body)}

    def record(
        self,
        *,
        promotion_path: str | Path,
        integrity_path: str | Path,
        checkpoint_path: str | Path,
        history_path: str | Path,
    ) -> dict[str, Any]:
        """Append newly crossed milestones without modifying prior snapshots."""
        promotion = self._read_json_object(
            promotion_path,
            expected_schema=self.PROMOTION_SCHEMA_VERSION,
            expected_phase="5.6.3",
        )
        integrity = self._read_json_object(
            integrity_path,
            expected_schema=self.INTEGRITY_SCHEMA_VERSION,
            expected_phase="5.6.5",
        )
        checkpoint = self._read_json_object(
            checkpoint_path,
            expected_schema=self.CHECKPOINT_SCHEMA_VERSION,
            expected_phase="5.6.2",
        )

        if (
            integrity.get("state") != "PASS"
            or integrity.get("integrity_ok") is not True
            or integrity.get("operational_state") != "HEALTHY"
        ):
            return {
                "phase": "5.6.8",
                "state": "BLOCKED_INTEGRITY",
                "history_mutated": False,
                "recorded_milestones": [],
            }

        sample = promotion.get("sample_gate")
        if not isinstance(sample, dict):
            raise ValueError("promotion report is missing sample_gate")
        signals = self._int_counter(sample.get("signals"), field="signals")
        candidate_pin = self._candidate_pin(promotion)
        output_path = Path(history_path)
        history_existed = output_path.exists()
        history = self._load_history(output_path, candidate_pin=candidate_pin)
        entries = history["milestones"]
        assert isinstance(entries, list)

        recorded = {
            self._int_counter(entry.get("milestone_signals"), field="milestone_signals")
            for entry in entries
            if isinstance(entry, dict)
        }
        due = [
            milestone
            for milestone in self.MILESTONES
            if signals >= milestone and milestone not in recorded
        ]

        previous_hash = (
            str(entries[-1].get("snapshot_hash"))
            if entries and isinstance(entries[-1], dict)
            else None
        )
        appended: list[int] = []
        for milestone in due:
            entry = self._build_entry(
                milestone=milestone,
                observed_signals=signals,
                promotion=promotion,
                integrity=integrity,
                checkpoint=checkpoint,
                previous_hash=previous_hash,
            )
            entries.append(entry)
            appended.append(milestone)
            previous_hash = str(entry["snapshot_hash"])

        self._verify_history(history, candidate_pin=candidate_pin)
        if appended or not history_existed:
            self._write_json(output_path, history)

        remaining = [
            milestone for milestone in self.MILESTONES if milestone not in recorded | set(appended)
        ]
        return {
            "phase": "5.6.8",
            "state": "RECORDED" if appended else "NO_MILESTONE_DUE",
            "history_mutated": bool(appended) or not history_existed,
            "recorded_milestones": appended,
            "observed_signals": signals,
            "next_milestone": remaining[0] if remaining else None,
            "history_path": str(output_path),
            "history": history,
        }
