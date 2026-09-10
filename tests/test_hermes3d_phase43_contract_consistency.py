from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.integrations.hermes3d.contracts import (
    EVENT_CONTRACT_VERSION,
    event_contract_manifest,
    validate_event_record,
)
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from scripts.verify_hermes3d_runtime_consistency import compare_overlay


def test_existing_journal_records_satisfy_event_contract(tmp_path: Path) -> None:
    journal = Hermes3DEventJournal(tmp_path / "events.jsonl")
    records = journal.publish_result(
        {
            "event": "BUY_FILLED",
            "strategy_id": "baseline",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "candle_ms": 123,
            "signal": {"action": "BUY"},
            "risk": {"approved": True},
            "position": {
                "order_id": "order-123",
                "symbol": "BTC/USDT",
                "side": "buy",
                "entry_price": 80_000,
                "quantity": 0.001,
                "take_profit": 82_000,
                "stop_loss": 79_000,
            },
        }
    )

    for record in records:
        validate_event_record(record)


def test_contract_manifest_is_stable_and_json_friendly() -> None:
    manifest = event_contract_manifest()

    assert manifest["version"] == EVENT_CONTRACT_VERSION == "1.0"
    assert "ORDER_OPEN" in manifest["trade_lifecycle_events"]
    assert "AGENT_ACTIVITY" in manifest["event_types"]
    assert manifest["required_payload_fields"]["ORDER_OPEN"] == ["order_id"]


def test_contract_rejects_naive_timestamp() -> None:
    record = {
        "event": "HEARTBEAT",
        "agent_id": "system",
        "generated_at": datetime.now().isoformat(),
        "payload": {},
    }

    with pytest.raises(ValueError, match="include a timezone"):
        validate_event_record(record)


def test_contract_accepts_timezone_aware_timestamp() -> None:
    validate_event_record(
        {
            "event": "HEARTBEAT",
            "agent_id": "system",
            "generated_at": datetime.now(UTC).isoformat(),
            "payload": {"read_only": True},
        }
    )


def test_contract_rejects_unknown_event_by_default() -> None:
    with pytest.raises(ValueError, match="unsupported Hermes3D event type"):
        validate_event_record(
            {
                "event": "ORDER_TELEPORTED",
                "agent_id": "positions",
                "generated_at": datetime.now(UTC).isoformat(),
                "payload": {},
            }
        )


def test_overlay_consistency_detects_missing_and_changed_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    runtime = tmp_path / "runtime"
    overlay = repo / "deploy" / "hermes3d" / "overlay"
    (overlay / "src").mkdir(parents=True)
    (runtime / "src").mkdir(parents=True)

    (overlay / "src" / "same.ts").write_text("same", encoding="utf-8")
    (runtime / "src" / "same.ts").write_text("same", encoding="utf-8")
    (overlay / "src" / "changed.ts").write_text("repo", encoding="utf-8")
    (runtime / "src" / "changed.ts").write_text("runtime", encoding="utf-8")
    (overlay / "src" / "missing.ts").write_text("required", encoding="utf-8")

    assert compare_overlay(repo, runtime) == [
        "changed:src/changed.ts",
        "missing:src/missing.ts",
    ]
