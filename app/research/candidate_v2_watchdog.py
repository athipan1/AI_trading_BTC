"""Independent Phase 5.7.4 watchdog: liveness != trade count."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CandidateV2WatchdogConfig:
    poll_seconds: int = 300
    heartbeat_warning_seconds: int = 900
    heartbeat_critical_seconds: int = 1800
    market_warning_seconds: int = 7200
    market_critical_seconds: int = 14400


class CandidateV2Watchdog:
    SCHEMA_VERSION = "candidate_v2_health_v1"
    HEARTBEAT_SCHEMA_VERSION = "candidate_v2_heartbeat_v1"

    def __init__(self, config: CandidateV2WatchdogConfig | None = None) -> None:
        self.config = config or CandidateV2WatchdogConfig()

    @staticmethod
    def _time(value: Any, name: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(f"{name} missing")
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError(f"{name} lacks timezone")
        return result.astimezone(UTC)

    def evaluate(
        self,
        *,
        integrity: dict[str, Any],
        heartbeat_path: str | Path,
        report_path: str | Path,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        states: list[str] = []
        issues: list[str] = []
        heartbeat_age: float | None = None
        data_lag: float | None = None
        watcher_state = "UNKNOWN"
        heartbeat: dict[str, Any] | None = None
        hb_file = Path(heartbeat_path)
        if hb_file.exists():
            try:
                loaded = json.loads(hb_file.read_text(encoding="utf-8"))
                if (
                    not isinstance(loaded, dict)
                    or loaded.get("schema_version") != self.HEARTBEAT_SCHEMA_VERSION
                ):
                    raise ValueError("invalid heartbeat schema")
                checked = self._time(loaded.get("last_attempt_at"), "last_attempt_at")
                heartbeat_age = (now - checked).total_seconds()
                if heartbeat_age < -120:
                    raise ValueError("heartbeat timestamp in future")
                heartbeat = loaded
                if heartbeat_age > self.config.heartbeat_critical_seconds:
                    watcher_state = "CRITICAL"
                    issues.append("WATCHER_HEARTBEAT_EXPIRED")
                elif heartbeat_age > self.config.heartbeat_warning_seconds:
                    watcher_state = "WARNING"
                    issues.append("WATCHER_HEARTBEAT_STALE")
                elif loaded.get("last_result") == "ERROR":
                    previous_success = loaded.get("last_success_at")
                    if previous_success is None:
                        success_age = float("inf")
                    else:
                        success_age = (now - self._time(previous_success, "last_success_at")).total_seconds()
                    watcher_state = (
                        "CRITICAL"
                        if success_age > self.config.heartbeat_critical_seconds
                        else "WARNING"
                    )
                    issues.append("WATCHER_CONSECUTIVE_FAILURES")
                elif loaded.get("last_result") == "SUCCESS":
                    if loaded.get("mode") != "watch":
                        watcher_state = "WARNING"
                        issues.append("WATCHER_ONE_SHOT_ONLY")
                    else:
                        watcher_state = "HEALTHY"
                else:
                    raise ValueError("unknown heartbeat status")
            except (OSError, ValueError, TypeError, KeyError):
                watcher_state = "CRITICAL"
                issues.append("WATCHER_HEARTBEAT_INVALID")
        else:
            issues.append("WATCHER_HEARTBEAT_MISSING")
        states.append(watcher_state)
        if integrity.get("integrity_state") == "FAIL":
            states.append("CRITICAL")
            issues.extend(str(x) for x in integrity.get("issues", []))
        elif integrity.get("integrity_state") == "WAITING":
            states.append("WAITING")
        elif integrity.get("integrity_state") == "PASS":
            states.append("HEALTHY")
        else:
            states.append("CRITICAL")
            issues.append("EVIDENCE_INTEGRITY_UNKNOWN")

        checkpoint = integrity.get("checkpoint") or {}
        until_str = checkpoint.get("last_processed_until")
        if until_str:
            try:
                until = self._time(until_str, "last_processed_until")
                data_lag = max(0.0, (now - until).total_seconds())
                if data_lag > self.config.market_critical_seconds:
                    states.append("CRITICAL")
                    issues.append("CHECKPOINT_H1_EXPIRED")
                elif data_lag > self.config.market_warning_seconds:
                    states.append("WARNING")
                    issues.append("CHECKPOINT_H1_STALE")
            except (ValueError, TypeError):
                states.append("CRITICAL")
                issues.append("CHECKPOINT_TIMESTAMP_INVALID")
        elif integrity.get("integrity_state") == "PASS":
            states.append("WARNING")
            issues.append("CHECKPOINT_TIMESTAMP_MISSING")

        source_state: str | None = None
        candidate_metrics: dict[str, Any] | None = None
        baseline_metrics: dict[str, Any] | None = None
        latest_file = Path(report_path)
        if latest_file.exists():
            try:
                report = json.loads(latest_file.read_text(encoding="utf-8"))
                if (
                    not isinstance(report, dict)
                    or report.get("schema_version") != "candidate_v2_forward_accumulation_v1"
                ):
                    raise ValueError("unsupported V2 report")
                if report.get("frozen_pin", {}).get("manifest_hash") != integrity.get("manifest_hash"):
                    raise ValueError("V2 report pin mismatch")
                if report.get("promotion_allowed") is not False or report.get("trade_execution") is not False:
                    raise ValueError("V2 report violates research isolation")
                source_state = str(report.get("state") or "UNKNOWN")
                if report.get("counts") == integrity.get("counts"):
                    # Metrics are presentation-only; never imply verified portfolio performance.
                    comparison = report.get("comparison") or {}
                    candidate_metrics = comparison.get("candidate_v2_full_replay")
                    baseline_metrics = comparison.get("canonical_rule_based_full_replay")
                else:
                    issues.append("REPORT_COUNTS_LAG_EVIDENCE")
            except (OSError, ValueError, TypeError, AttributeError):
                states.append("WARNING")
                issues.append("LATEST_REPORT_INVALID")
        elif integrity.get("integrity_state") == "PASS":
            states.append("WARNING")
            issues.append("LATEST_REPORT_MISSING")

        state = next((x for x in ("CRITICAL", "WARNING", "UNKNOWN", "WAITING") if x in states), "HEALTHY")
        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.7.4",
            "observed_at": now.isoformat(),
            "operational_state": state,
            "watcher_state": watcher_state,
            "heartbeat_age_seconds": None if heartbeat_age is None else round(heartbeat_age, 2),
            "market_data_lag_seconds": None if data_lag is None else round(data_lag, 2),
            "last_success_at": heartbeat.get("last_success_at") if heartbeat else None,
            "last_attempt_at": heartbeat.get("last_attempt_at") if heartbeat else None,
            "source_accumulator_state": source_state,
            "integrity": integrity,
            "counts": integrity.get("counts"),
            "metrics": {"candidate_v2": candidate_metrics, "baseline": baseline_metrics},
            "issues": sorted(set(issues)),
            "research_only": True,
            "trade_execution": False,
            "promotion_allowed": False,
            "production_mutation": False,
        }