from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OOSAlertSnapshot:
    oos_signals: int
    required_signals: int
    policy_selected: int
    required_policy_selected: int
    promotion_state: str
    promotion_allowed: bool
    integrity_state: str
    operational_state: str
    last_processed_until: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "oos_signals": self.oos_signals,
            "required_signals": self.required_signals,
            "policy_selected": self.policy_selected,
            "required_policy_selected": self.required_policy_selected,
            "promotion_state": self.promotion_state,
            "promotion_allowed": self.promotion_allowed,
            "integrity_state": self.integrity_state,
            "operational_state": self.operational_state,
            "last_processed_until": self.last_processed_until,
        }


def _read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _counter(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"promotion {name} counter is invalid")
    return value


def build_snapshot(
    *,
    promotion_path: str | Path,
    integrity_path: str | Path,
    checkpoint_path: str | Path,
) -> OOSAlertSnapshot:
    promotion = _read_json(promotion_path)
    integrity = _read_json(integrity_path)
    checkpoint = _read_json(checkpoint_path)

    sample = promotion.get("sample_gate")
    gate_manifest = promotion.get("gate_manifest")
    if not isinstance(sample, dict) or not isinstance(gate_manifest, dict):
        raise ValueError("promotion sample gate contract is invalid")

    performance_gate = gate_manifest.get("performance_gate")
    if not isinstance(performance_gate, dict):
        raise ValueError("promotion frozen performance gate contract is invalid")

    signals = _counter(sample.get("signals"), name="signals")
    policy_selected = _counter(sample.get("policy_selected_trades"), name="policy_selected_trades")
    required_signals = _counter(performance_gate.get("minimum_oos_signals"), name="minimum_oos_signals")
    required_policy_selected = _counter(
        performance_gate.get("minimum_policy_selected_trades"), name="minimum_policy_selected_trades"
    )

    state = str(promotion.get("state") or promotion.get("evidence_state") or "UNKNOWN")
    promotion_allowed = bool(promotion.get("promotion_allowed", False))

    return OOSAlertSnapshot(
        oos_signals=signals,
        required_signals=required_signals,
        policy_selected=policy_selected,
        required_policy_selected=required_policy_selected,
        promotion_state=state,
        promotion_allowed=promotion_allowed,
        integrity_state=str(integrity.get("state", "UNKNOWN")),
        operational_state=str(integrity.get("operational_state", "UNKNOWN")),
        last_processed_until=str(checkpoint.get("last_processed_until") or "unknown"),
    )


def should_notify(current: OOSAlertSnapshot, previous: dict[str, Any] | None) -> bool:
    if previous is None:
        return True
    watched = (
        "oos_signals",
        "policy_selected",
        "promotion_state",
        "promotion_allowed",
        "integrity_state",
        "operational_state",
    )
    current_dict = current.as_dict()
    return any(previous.get(key) != current_dict[key] for key in watched)


def format_oos_line_message(snapshot: OOSAlertSnapshot) -> str:
    lock = "FROZEN 🔒"
    return "\n".join(
        [
            "AI Trading BTC | OOS Update",
            "",
            f"OOS Signals: {snapshot.oos_signals} / {snapshot.required_signals}",
            f"Policy Selected: {snapshot.policy_selected} / {snapshot.required_policy_selected}",
            "",
            f"Promotion: {snapshot.promotion_state}",
            f"Promotion Allowed: {snapshot.promotion_allowed}",
            f"Integrity: {snapshot.integrity_state}",
            f"Operational: {snapshot.operational_state}",
            "",
            f"Model: {lock}",
            f"Policy: {lock}",
            f"Threshold: {lock}",
            "",
            f"Last processed: {snapshot.last_processed_until}",
        ]
    )


def format_daily_heartbeat_message(snapshot: OOSAlertSnapshot, *, evidence_changed: bool) -> str:
    evidence_status = "UPDATED" if evidence_changed else "NO NEW EVIDENCE"
    return "\n".join(
        [
            "AI Trading BTC | OOS Daily Heartbeat 💓",
            "",
            f"Evidence: {evidence_status}",
            f"OOS Signals: {snapshot.oos_signals} / {snapshot.required_signals}",
            f"Policy Selected: {snapshot.policy_selected} / {snapshot.required_policy_selected}",
            "",
            f"Promotion: {snapshot.promotion_state}",
            f"Integrity: {snapshot.integrity_state}",
            f"Operational: {snapshot.operational_state}",
            "",
            "Model / Policy / Threshold: FROZEN 🔒",
            f"Last processed: {snapshot.last_processed_until}",
        ]
    )


def load_alert_state(path: str | Path) -> dict[str, Any] | None:
    state_path = Path(path)
    if not state_path.exists():
        return None
    return _read_json(state_path)


def write_alert_state(path: str | Path, snapshot: OOSAlertSnapshot) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(f"{state_path.suffix}.tmp")
    temporary.write_text(
        json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(state_path)
