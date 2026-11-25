"""Pure alert transition policy for Phase 5.7.4; sending is delegated to LINE notifier."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class CandidateV2AlertPolicy:
    REPEAT_SECONDS = 3600

    @staticmethod
    def decision(
        health: dict[str, Any],
        previous: dict[str, Any] | None,
        *,
        now: datetime | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        state = str(health.get("operational_state", "UNKNOWN"))
        if state not in {"HEALTHY", "WAITING", "WARNING", "CRITICAL", "UNKNOWN"}:
            state = "UNKNOWN"
        previous = previous or {}
        prior = str(previous.get("last_notified_state") or "")
        last = previous.get("last_notified_at")
        age = float("inf")
        if isinstance(last, str):
            try:
                ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if ts.tzinfo is not None:
                    age = max(0.0, (current - ts.astimezone(UTC)).total_seconds())
            except ValueError:
                pass
        kind: str | None = None
        if state in {"WARNING", "CRITICAL"}:
            if state != prior or age >= CandidateV2AlertPolicy.REPEAT_SECONDS:
                kind = "ALERT"
        elif state in {"HEALTHY", "WAITING"} and prior in {"WARNING", "CRITICAL"}:
            if int(previous.get("recovery_checks", 0)) + 1 >= 2:
                kind = "RECOVERY"
        next_state = {
            "last_notified_state": state if kind else prior,
            "last_notified_at": current.isoformat() if kind else last,
            "recovery_checks": (
                0 if kind or state in {"WARNING", "CRITICAL", "UNKNOWN"}
                else int(previous.get("recovery_checks", 0)) + 1
            ),
        }
        return kind, next_state

    @staticmethod
    def message(health: dict[str, Any], kind: str) -> str:
        state = str(health.get("operational_state") or "UNKNOWN")
        counts = health.get("counts") or {}
        issues = health.get("issues") or []
        label = "RECOVERED" if kind == "RECOVERY" else state
        return "\n".join([
            "AI Trading BTC | Candidate V2 Research",
            f"Monitoring: {label}",
            "Mode: RESEARCH ONLY (no execution / promotion)",
            f"Frozen policy: {health.get('integrity', {}).get('policy_name') or 'unknown'}",
            f"Candidate closed: {counts.get('candidate_v2_closed', 0)}",
            f"Baseline closed: {counts.get('canonical_rule_based_closed', 0)}",
            f"Heartbeat age (seconds): {health.get('heartbeat_age_seconds')}",
            f"Issues: {', '.join(str(x) for x in issues[:4]) if issues else 'none'}",
        ])