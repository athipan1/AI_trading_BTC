from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.research.oos_line_alerts import (
    build_snapshot,
    format_oos_line_message,
    should_notify,
    write_alert_state,
)


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _promotion(*, signals: int = 9, policy_selected: int = 7, state: str = "TOO_EARLY") -> dict[str, object]:
    return {
        "schema_version": "oos_promotion_gate_schema_v1",
        "state": state,
        "evidence_state": "EVIDENCE_READY" if signals >= 20 and policy_selected >= 10 else "TOO_EARLY",
        "promotion_allowed": False,
        "sample_gate": {
            "ready": signals >= 20 and policy_selected >= 10,
            "checks": {},
            "signals": signals,
            "policy_selected_trades": policy_selected,
        },
        "gate_manifest": {
            "performance_gate": {
                "minimum_oos_signals": 20,
                "minimum_policy_selected_trades": 10,
            }
        },
    }


def test_snapshot_message_and_dedup(tmp_path: Path) -> None:
    promotion = tmp_path / "promotion.json"
    integrity = tmp_path / "integrity.json"
    checkpoint = tmp_path / "checkpoint.json"
    state = tmp_path / "state.json"

    _write(promotion, _promotion())
    _write(integrity, {"state": "PASS", "operational_state": "HEALTHY"})
    _write(checkpoint, {"last_processed_until": "2026-09-14T00:00:00+00:00"})

    snapshot = build_snapshot(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
    )
    assert snapshot.oos_signals == 9
    assert snapshot.required_signals == 20
    assert snapshot.policy_selected == 7
    assert snapshot.required_policy_selected == 10
    assert snapshot.promotion_state == "TOO_EARLY"
    assert snapshot.integrity_state == "PASS"
    assert should_notify(snapshot, None) is True

    message = format_oos_line_message(snapshot)
    assert "OOS Signals: 9 / 20" in message
    assert "Policy Selected: 7 / 10" in message
    assert "Integrity: PASS" in message

    write_alert_state(state, snapshot)
    previous = json.loads(state.read_text(encoding="utf-8"))
    assert should_notify(snapshot, previous) is False


def test_counter_or_gate_change_triggers_alert(tmp_path: Path) -> None:
    promotion = tmp_path / "promotion.json"
    integrity = tmp_path / "integrity.json"
    checkpoint = tmp_path / "checkpoint.json"
    _write(promotion, _promotion(signals=20, policy_selected=10, state="EVIDENCE_READY"))
    _write(integrity, {"state": "PASS", "operational_state": "HEALTHY"})
    _write(checkpoint, {"last_processed_until": "2026-09-16T00:00:00+00:00"})
    snapshot = build_snapshot(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
    )
    previous = snapshot.as_dict() | {"oos_signals": 19, "promotion_state": "TOO_EARLY"}
    assert should_notify(snapshot, previous) is True


def test_integrity_incident_triggers_alert(tmp_path: Path) -> None:
    promotion = tmp_path / "promotion.json"
    integrity = tmp_path / "integrity.json"
    checkpoint = tmp_path / "checkpoint.json"
    _write(promotion, _promotion())
    _write(integrity, {"state": "FAIL", "operational_state": "HEALTHY"})
    _write(checkpoint, {"last_processed_until": "2026-09-16T00:00:00+00:00"})
    snapshot = build_snapshot(
        promotion_path=promotion,
        integrity_path=integrity,
        checkpoint_path=checkpoint,
    )
    previous = snapshot.as_dict() | {"integrity_state": "PASS"}
    assert should_notify(snapshot, previous) is True


def test_rejects_noncanonical_counter_shape(tmp_path: Path) -> None:
    promotion = tmp_path / "promotion.json"
    integrity = tmp_path / "integrity.json"
    checkpoint = tmp_path / "checkpoint.json"
    payload = _promotion()
    sample = payload["sample_gate"]
    assert isinstance(sample, dict)
    sample["signals"] = {"current": 9, "required": 20}
    _write(promotion, payload)
    _write(integrity, {"state": "PASS", "operational_state": "HEALTHY"})
    _write(checkpoint, {"last_processed_until": "2026-09-16T00:00:00+00:00"})

    with pytest.raises(ValueError, match="signals counter is invalid"):
        build_snapshot(
            promotion_path=promotion,
            integrity_path=integrity,
            checkpoint_path=checkpoint,
        )
