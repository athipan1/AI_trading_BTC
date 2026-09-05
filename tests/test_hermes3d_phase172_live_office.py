from __future__ import annotations

from pathlib import Path

from app.integrations.hermes3d.journal import Hermes3DEventJournal
from scripts.validate_hermes3d_live_office import emit_validation_sequence


def test_phase172_emits_only_observability_events(tmp_path: Path) -> None:
    journal_path = tmp_path / "hermes3d-events.jsonl"

    published = emit_validation_sequence(
        journal_path=journal_path,
        strategy_id="triple_ema",
        interval_seconds=0,
    )

    assert [item["event"] for item in published] == [
        "BUY_READY",
        "RISK_PASS",
        "ORDER_OPEN",
    ]
    assert [item["agent_id"] for item in published] == [
        "triple_ema",
        "risk-manager",
        "positions",
    ]
    assert all(item["payload"]["validation"] is True for item in published)
    assert all(item["payload"]["read_only"] is True for item in published)

    persisted = Hermes3DEventJournal(journal_path).read_recent()
    assert persisted == published


def test_phase172_validation_order_has_zero_execution_quantity(tmp_path: Path) -> None:
    journal_path = tmp_path / "hermes3d-events.jsonl"

    published = emit_validation_sequence(
        journal_path=journal_path,
        strategy_id="baseline",
        interval_seconds=0,
    )

    order_event = published[-1]
    assert order_event["event"] == "ORDER_OPEN"
    assert order_event["payload"]["quantity"] == 0
    assert order_event["payload"]["entry_price"] == 0
    assert str(order_event["payload"]["order_id"]).startswith("phase17-validation-")
