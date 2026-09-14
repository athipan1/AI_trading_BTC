from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvidenceIntegrityConfig:
    boundary_iso: str = "2026-09-01T00:00:00+00:00"
    warmup_hours: int = 288
    stale_after_seconds: float = 108_000.0


class EvidenceIntegrityAuditor:
    """Phase 5.6.5 read-only audit of Forward OOS evidence and checkpoint lineage."""

    SCHEMA_VERSION = "evidence_integrity_schema_v1"
    STATE_SCHEMA_VERSION = "evidence_integrity_state_schema_v1"
    CHECKPOINT_SCHEMA_VERSION = "forward_oos_checkpoint_schema_v1"
    OOS_STORE_SCHEMA_VERSION = "historical_research_store_v1"
    _PIN_FIELDS = (
        "manifest_hash",
        "policy_hash",
        "model_fingerprint",
        "discovery_cutoff",
    )
    _TRADE_METADATA_FIELDS = {
        "data_origin",
        "replay_schema_version",
        "dataset_run_id",
        "source",
        "git_commit",
    }

    def __init__(
        self,
        *,
        config: EvidenceIntegrityConfig | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config or EvidenceIntegrityConfig()
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _read_json_object(path: Path, label: str) -> dict[str, Any]:
        if not path.exists():
            raise ValueError(f"{label} is missing: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"unable to read {label}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{label} must contain a JSON object")
        return payload

    @staticmethod
    def _canonical_hash(payload: Any) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _core_trade(cls, trade: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in trade.items()
            if key not in cls._TRADE_METADATA_FIELDS
        }

    @classmethod
    def trade_fingerprints(cls, trades: list[dict[str, Any]]) -> dict[str, str]:
        fingerprints: dict[str, str] = {}
        for trade in trades:
            order_id = str(trade.get("order_id") or "").strip()
            if not order_id:
                continue
            fingerprints[order_id] = cls._canonical_hash(cls._core_trade(trade))
        return fingerprints

    @staticmethod
    def load_state(path: str | Path) -> dict[str, Any] | None:
        state_path = Path(path)
        if not state_path.exists():
            return None
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Phase 5.6.5 state must contain a JSON object")
        if payload.get("schema_version") != EvidenceIntegrityAuditor.STATE_SCHEMA_VERSION:
            raise ValueError("unsupported Phase 5.6.5 state schema")
        return payload

    @staticmethod
    def write_json(path: str | Path, payload: dict[str, Any]) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(f"{output_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output_path)

    def _expected_pin(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            **{field: manifest.get(field) for field in self._PIN_FIELDS},
            "boundary_iso": self.config.boundary_iso,
            "warmup_hours": self.config.warmup_hours,
        }

    def audit(
        self,
        *,
        manifest_path: str | Path,
        oos_store_path: str | Path,
        checkpoint_path: str | Path,
        previous_state: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        manifest_file = Path(manifest_path)
        oos_file = Path(oos_store_path)
        checkpoint_file = Path(checkpoint_path)

        manifest = self._read_json_object(manifest_file, "frozen manifest")
        oos_store = self._read_json_object(oos_file, "OOS store")
        checkpoint = self._read_json_object(checkpoint_file, "Phase 5.6.2 checkpoint")

        trades_raw = oos_store.get("trades", [])
        if not isinstance(trades_raw, list):
            raise ValueError("OOS store trades must be a list")
        trades = [dict(item) for item in trades_raw if isinstance(item, dict)]
        fingerprints = self.trade_fingerprints(trades)

        order_ids = [str(item.get("order_id") or "").strip() for item in trades]
        nonempty_order_ids = [value for value in order_ids if value]
        order_id_counts = Counter(nonempty_order_ids)
        duplicate_order_ids = sorted(
            order_id for order_id, count in order_id_counts.items() if count > 1
        )
        missing_order_id_count = len(order_ids) - len(nonempty_order_ids)

        boundary_ms = int(self._parse_iso(self.config.boundary_iso).timestamp() * 1000)
        timestamps = [int(item.get("entry_feature_timestamp_ms") or 0) for item in trades]
        before_boundary = [value for value in timestamps if value < boundary_ms]
        invalid_timestamp_count = sum(value <= 0 for value in timestamps)

        oos_store_schema_ok = oos_store.get("schema_version") == self.OOS_STORE_SCHEMA_VERSION
        checkpoint_schema_ok = checkpoint.get("schema_version") == self.CHECKPOINT_SCHEMA_VERSION
        checkpoint_count = int(checkpoint.get("last_oos_trade_count", -1))
        store_count = len(trades)
        count_matches = checkpoint_count == store_count
        expected_pin = self._expected_pin(manifest)
        actual_pin = checkpoint.get("frozen_pin")
        frozen_pin_matches = actual_pin == expected_pin

        last_processed_raw = str(checkpoint.get("last_processed_until") or "")
        last_processed = self._parse_iso(last_processed_raw) if last_processed_raw else None
        now = self._now_factory().astimezone(UTC)
        age_seconds = None if last_processed is None else max(0.0, (now - last_processed).total_seconds())
        freshness_ok = age_seconds is not None and age_seconds <= self.config.stale_after_seconds

        rollback_checks = {
            "run_count_monotonic": True,
            "oos_trade_count_monotonic": True,
            "last_processed_until_monotonic": True,
            "immutable_existing_trades": True,
        }
        changed_existing_order_ids: list[str] = []
        if previous_state is not None:
            previous_run_count = int(previous_state.get("run_count", 0))
            previous_trade_count = int(previous_state.get("oos_trade_count", 0))
            previous_until_raw = str(previous_state.get("last_processed_until") or "")
            current_run_count = int(checkpoint.get("run_count", 0))
            rollback_checks["run_count_monotonic"] = current_run_count >= previous_run_count
            rollback_checks["oos_trade_count_monotonic"] = store_count >= previous_trade_count
            if previous_until_raw and last_processed is not None:
                rollback_checks["last_processed_until_monotonic"] = (
                    last_processed >= self._parse_iso(previous_until_raw)
                )

            previous_fingerprints = previous_state.get("trade_fingerprints", {})
            if isinstance(previous_fingerprints, dict):
                changed_existing_order_ids = sorted(
                    order_id
                    for order_id, fingerprint in previous_fingerprints.items()
                    if order_id not in fingerprints or fingerprints.get(order_id) != fingerprint
                )
                rollback_checks["immutable_existing_trades"] = not changed_existing_order_ids

        checks = {
            "oos_store_schema": oos_store_schema_ok,
            "checkpoint_schema": checkpoint_schema_ok,
            "frozen_pin_matches_manifest": frozen_pin_matches,
            "checkpoint_count_matches_store": count_matches,
            "order_ids_present": missing_order_id_count == 0,
            "order_ids_unique": not duplicate_order_ids,
            "timestamps_valid": invalid_timestamp_count == 0,
            "all_trades_after_boundary": not before_boundary,
            **rollback_checks,
        }
        integrity_ok = all(checks.values())
        operational_state = "HEALTHY" if freshness_ok else "STALE"
        state = "PASS" if integrity_ok else "FAIL"

        report = {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.6.5",
            "research_only": True,
            "read_only_audit": True,
            "production_position_store_mutated": False,
            "production_execution_mutated": False,
            "optimization_performed": False,
            "oos_retuning_performed": False,
            "state": state,
            "operational_state": operational_state,
            "integrity_ok": integrity_ok,
            "checks": checks,
            "evidence": {
                "oos_trade_count": store_count,
                "checkpoint_oos_trade_count": checkpoint_count,
                "run_count": int(checkpoint.get("run_count", 0)),
                "last_processed_until": last_processed_raw or None,
                "age_seconds": age_seconds,
                "boundary_iso": self.config.boundary_iso,
                "warmup_hours": self.config.warmup_hours,
            },
            "violations": {
                "duplicate_order_ids": duplicate_order_ids,
                "missing_order_id_count": missing_order_id_count,
                "before_boundary_count": len(before_boundary),
                "invalid_timestamp_count": invalid_timestamp_count,
                "changed_existing_order_ids": changed_existing_order_ids,
            },
            "hashes": {
                "manifest": self._canonical_hash(manifest),
                "oos_store": self._canonical_hash(oos_store),
                "checkpoint": self._canonical_hash(checkpoint),
            },
            "frozen_pin": actual_pin,
        }

        next_state = {
            "schema_version": self.STATE_SCHEMA_VERSION,
            "phase": "5.6.5",
            "run_count": int(checkpoint.get("run_count", 0)),
            "oos_trade_count": store_count,
            "last_processed_until": last_processed_raw or None,
            "trade_fingerprints": fingerprints,
            "hashes": report["hashes"],
        }
        return report, next_state
