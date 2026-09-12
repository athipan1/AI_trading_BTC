from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.research.forward_oos_automation import (
    ForwardOOSAutomation,
    ForwardOOSAutomationConfig,
)
from app.research.historical_store import HistoricalResearchStore


def _manifest() -> dict[str, object]:
    return {
        "manifest_hash": "manifest-1",
        "policy_hash": "policy-1",
        "model_fingerprint": "model-1",
        "discovery_cutoff": "2026-08-30T15:00:00+00:00",
    }


def test_last_closed_hour_and_auto_until_are_safe() -> None:
    automation = ForwardOOSAutomation()
    now = datetime(2026, 9, 12, 14, 37, 55, tzinfo=UTC)

    assert automation.last_closed_hour(now).isoformat() == "2026-09-12T14:00:00+00:00"
    assert automation.resolve_until(None, now=now) == "2026-09-12T14:00:00+00:00"

    with pytest.raises(ValueError, match="latest fully closed H1"):
        automation.resolve_until("2026-09-12T15:00:00+00:00", now=now)


def test_checkpoint_pin_rejects_frozen_contract_drift(tmp_path: Path) -> None:
    automation = ForwardOOSAutomation(
        config=ForwardOOSAutomationConfig(warmup_hours=288)
    )
    checkpoint = {
        "schema_version": automation.CHECKPOINT_SCHEMA_VERSION,
        "frozen_pin": {
            **automation.manifest_pin(_manifest()),
            "boundary_iso": "2026-09-01T00:00:00+00:00",
            "warmup_hours": 288,
        },
        "last_processed_until": "2026-09-12T00:00:00+00:00",
        "run_count": 1,
    }
    automation.write_checkpoint(tmp_path / "checkpoint.json", checkpoint)
    loaded = automation.load_checkpoint(tmp_path / "checkpoint.json")
    automation.verify_checkpoint_pin(loaded, _manifest())

    changed = dict(_manifest())
    changed["policy_hash"] = "policy-2"
    with pytest.raises(ValueError, match="frozen contract differs"):
        automation.verify_checkpoint_pin(loaded, changed)


def test_evidence_state_waits_for_minimum_evidence() -> None:
    automation = ForwardOOSAutomation()

    too_early = {
        "evidence_acceptance": {
            "minimum_oos_signals": False,
            "minimum_policy_selected_trades": False,
        },
        "validation_status": "FAIL",
        "superiority_status": "FAIL",
    }
    assert automation.evidence_state(too_early, "TOO_EARLY") == "TOO_EARLY"

    valid_not_superior = {
        "evidence_acceptance": {
            "minimum_oos_signals": True,
            "minimum_policy_selected_trades": True,
        },
        "validation_status": "PASS",
        "superiority_status": "FAIL",
    }
    assert automation.evidence_state(valid_not_superior, "EARLY_SIGNAL") == "EVALUATE"

    superior = dict(valid_not_superior)
    superior["superiority_status"] = "PASS"
    assert automation.evidence_state(superior, "INTERMEDIATE") == "PASS"

    failed = dict(valid_not_superior)
    failed["validation_status"] = "FAIL"
    assert automation.evidence_state(failed, "EARLY_SIGNAL") == "FAIL"


def test_no_new_data_short_circuits_without_replay(tmp_path: Path) -> None:
    class ExplodingAccumulator:
        def accumulate(self, **_: object) -> dict[str, object]:
            raise AssertionError("accumulator must not run when no new interval exists")

    automation = ForwardOOSAutomation(accumulator=ExplodingAccumulator())  # type: ignore[arg-type]
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = {
        "schema_version": automation.CHECKPOINT_SCHEMA_VERSION,
        "phase": "5.6.2",
        "frozen_pin": automation._checkpoint_pin(_manifest()),
        "last_processed_until": "2026-09-12T14:00:00+00:00",
        "last_oos_trade_count": 0,
        "last_evidence_stage": "TOO_EARLY",
        "last_state": "TOO_EARLY",
        "run_count": 3,
    }
    automation.write_checkpoint(checkpoint_path, checkpoint)
    store = HistoricalResearchStore(tmp_path / "oos.json")

    report = automation.run(
        discovery_trades=[],
        manifest=_manifest(),
        oos_store=store,
        checkpoint_path=checkpoint_path,
        market_data=object(),  # type: ignore[arg-type]
        replay_config=object(),  # type: ignore[arg-type]
        dataset_run_id="run",
        requested_until="2026-09-12T14:00:00+00:00",
        now=datetime(2026, 9, 12, 14, 30, tzinfo=UTC),
    )

    assert report["state"] == "NO_NEW_DATA"
    assert report["checkpoint_run_count"] == 3
    assert report["oos_trade_count"] == 0
