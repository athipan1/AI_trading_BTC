from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.research.forward_oos import ForwardOOSAccumulator, ForwardOOSConfig
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import HistoricalReplayConfig
from app.research.historical_store import HistoricalResearchStore


@dataclass(frozen=True)
class ForwardOOSAutomationConfig:
    boundary_iso: str = "2026-09-01T00:00:00+00:00"
    warmup_hours: int = 288
    too_early_trade_count: int = 20
    intermediate_trade_count: int = 50
    stronger_evidence_trade_count: int = 100


class ForwardOOSAutomation:
    """Phase 5.6.2 orchestration around the frozen Phase 5.6.1 pipeline."""

    SCHEMA_VERSION = "forward_oos_automation_schema_v1"
    CHECKPOINT_SCHEMA_VERSION = "forward_oos_checkpoint_schema_v1"
    _PIN_FIELDS = (
        "manifest_hash",
        "policy_hash",
        "model_fingerprint",
        "discovery_cutoff",
    )

    def __init__(
        self,
        *,
        config: ForwardOOSAutomationConfig | None = None,
        accumulator: ForwardOOSAccumulator | None = None,
    ) -> None:
        self.config = config or ForwardOOSAutomationConfig()
        self.accumulator = accumulator or ForwardOOSAccumulator(
            config=ForwardOOSConfig(
                boundary_iso=self.config.boundary_iso,
                warmup_hours=self.config.warmup_hours,
                too_early_trade_count=self.config.too_early_trade_count,
                intermediate_trade_count=self.config.intermediate_trade_count,
                stronger_evidence_trade_count=self.config.stronger_evidence_trade_count,
            )
        )

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def last_closed_hour(now: datetime | None = None) -> datetime:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
        return current.replace(minute=0, second=0, microsecond=0)

    def resolve_until(self, requested_until: str | None, *, now: datetime | None = None) -> str:
        latest_safe = self.last_closed_hour(now)
        if requested_until is None:
            return latest_safe.isoformat()
        requested = self._parse_iso(requested_until)
        if requested > latest_safe:
            raise ValueError(
                "Phase 5.6.2 --until cannot be later than the latest fully closed H1 boundary"
            )
        if requested <= self._parse_iso(self.config.boundary_iso):
            raise ValueError("Phase 5.6.2 --until must be after the frozen OOS boundary")
        return requested.isoformat()

    def manifest_pin(self, manifest: dict[str, Any]) -> dict[str, Any]:
        missing = [field for field in self._PIN_FIELDS if not manifest.get(field)]
        if missing:
            raise ValueError(f"Phase 5.6.2 manifest is missing frozen fields: {missing}")
        return {field: manifest[field] for field in self._PIN_FIELDS}

    def _checkpoint_pin(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            **self.manifest_pin(manifest),
            "boundary_iso": self.config.boundary_iso,
            "warmup_hours": self.config.warmup_hours,
        }

    def load_checkpoint(self, path: str | Path) -> dict[str, Any] | None:
        checkpoint_path = Path(path)
        if not checkpoint_path.exists():
            return None
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Phase 5.6.2 checkpoint must contain a JSON object")
        if payload.get("schema_version") != self.CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("unsupported Phase 5.6.2 checkpoint schema")
        return payload

    def write_checkpoint(self, path: str | Path, payload: dict[str, Any]) -> None:
        checkpoint_path = Path(path)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = checkpoint_path.with_suffix(f"{checkpoint_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(checkpoint_path)

    def verify_checkpoint_pin(
        self,
        checkpoint: dict[str, Any] | None,
        manifest: dict[str, Any],
    ) -> None:
        if checkpoint is None:
            return
        expected = self._checkpoint_pin(manifest)
        actual = checkpoint.get("frozen_pin")
        if actual != expected:
            raise ValueError("Phase 5.6.2 frozen contract differs from the persisted checkpoint")

    @staticmethod
    def evidence_state(validation: dict[str, Any], evidence_stage: str) -> str:
        evidence = validation.get("evidence_acceptance", {})
        if evidence_stage == "TOO_EARLY" or not all(bool(value) for value in evidence.values()):
            return "TOO_EARLY"
        validation_status = validation.get("validation_status")
        superiority_status = validation.get("superiority_status")
        if validation_status == "PASS" and superiority_status == "PASS":
            return "PASS"
        if validation_status == "PASS":
            return "EVALUATE"
        return "FAIL"

    def _no_new_data_report(
        self,
        *,
        checkpoint: dict[str, Any],
        requested_until: str,
        oos_trade_count: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.6.2",
            "research_only": True,
            "production_position_store_mutated": False,
            "optimization_performed": False,
            "oos_retuning_performed": False,
            "state": "NO_NEW_DATA",
            "requested_until": requested_until,
            "last_processed_until": checkpoint.get("last_processed_until"),
            "oos_trade_count": oos_trade_count,
            "frozen_pin": checkpoint.get("frozen_pin"),
            "checkpoint_run_count": int(checkpoint.get("run_count", 0)),
        }

    def run(
        self,
        *,
        discovery_trades: list[dict[str, Any]],
        manifest: dict[str, Any],
        oos_store: HistoricalResearchStore,
        checkpoint_path: str | Path,
        market_data: HistoricalMarketDataService,
        replay_config: HistoricalReplayConfig,
        dataset_run_id: str,
        requested_until: str | None = None,
        git_commit: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        until_iso = self.resolve_until(requested_until, now=now)
        checkpoint = self.load_checkpoint(checkpoint_path)
        self.verify_checkpoint_pin(checkpoint, manifest)

        if checkpoint is not None:
            previous_until = checkpoint.get("last_processed_until")
            if previous_until and self._parse_iso(until_iso) <= self._parse_iso(str(previous_until)):
                return self._no_new_data_report(
                    checkpoint=checkpoint,
                    requested_until=until_iso,
                    oos_trade_count=len(oos_store.load()),
                )

        phase561 = self.accumulator.accumulate(
            discovery_trades=discovery_trades,
            manifest=manifest,
            oos_store=oos_store,
            market_data=market_data,
            until_iso=until_iso,
            replay_config=replay_config,
            dataset_run_id=dataset_run_id,
            git_commit=git_commit,
        )
        accumulation = phase561["accumulation"]
        validation = phase561["phase56_validation"]
        evidence_stage = str(accumulation["evidence_stage"])
        state = self.evidence_state(validation, evidence_stage)
        run_count = int(checkpoint.get("run_count", 0)) + 1 if checkpoint else 1
        updated_checkpoint = {
            "schema_version": self.CHECKPOINT_SCHEMA_VERSION,
            "phase": "5.6.2",
            "frozen_pin": self._checkpoint_pin(manifest),
            "last_processed_until": until_iso,
            "last_oos_trade_count": int(accumulation["oos_trade_count"]),
            "last_evidence_stage": evidence_stage,
            "last_state": state,
            "run_count": run_count,
        }
        self.write_checkpoint(checkpoint_path, updated_checkpoint)

        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.6.2",
            "research_only": True,
            "production_position_store_mutated": False,
            "optimization_performed": False,
            "oos_retuning_performed": False,
            "method": "automated_frozen_forward_oos_evidence_accumulation",
            "state": state,
            "config": asdict(self.config),
            "requested_until": until_iso,
            "frozen_pin": updated_checkpoint["frozen_pin"],
            "checkpoint": {
                "run_count": run_count,
                "last_processed_until": until_iso,
            },
            "accumulation": accumulation,
            "phase56_validation": validation,
            "validation_status": phase561["validation_status"],
            "superiority_status": phase561["superiority_status"],
        }
