from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.router import build_hermes3d_router
from app.integrations.hermes3d.simulator import Hermes3DValidationEventSimulator


class _Reader:
    def registry(self) -> dict[str, Any]:
        return {"agents": []}

    def state(self) -> dict[str, Any]:
        return {"read_only": True, "permissions": {"trade_execution": False}}


def _client(tmp_path: Path, *, enabled: bool) -> tuple[TestClient, Hermes3DEventJournal]:
    journal = Hermes3DEventJournal(tmp_path / "events.jsonl")
    simulator = Hermes3DValidationEventSimulator(journal)
    app = FastAPI()
    app.include_router(
        build_hermes3d_router(
            _Reader(),
            validation_simulator=simulator,
            validation_simulator_enabled=enabled,
        )
    )
    return TestClient(app), journal


def test_validation_simulator_is_disabled_by_default(tmp_path: Path) -> None:
    client, journal = _client(tmp_path, enabled=False)

    response = client.post("/validation/events/ORDER_OPEN")

    assert response.status_code == 404
    assert journal.read_recent() == []


def test_validation_simulator_publishes_only_to_journal(tmp_path: Path) -> None:
    client, journal = _client(tmp_path, enabled=True)

    response = client.post("/validation/events/ORDER_OPEN")

    assert response.status_code == 200
    body = response.json()
    assert body["published"] is True
    assert body["read_only"] is True
    assert body["trade_execution"] is False
    assert body["event"]["event"] == "ORDER_OPEN"
    assert body["event"]["agent_id"] == "positions"
    assert body["event"]["payload"]["validation"] is True
    records = journal.read_recent()
    assert len(records) == 1
    assert records[0] == body["event"]


def test_validation_simulator_covers_visual_event_contract(tmp_path: Path) -> None:
    client, journal = _client(tmp_path, enabled=True)
    expected = {
        "BUY_READY",
        "SHORT_READY",
        "RISK_PASS",
        "ORDER_OPEN",
        "TP_HIT",
        "SL_HIT",
        "CIRCUIT_BREAKER",
    }

    for event_name in sorted(expected):
        response = client.post(f"/validation/events/{event_name}")
        assert response.status_code == 200

    assert {row["event"] for row in journal.read_recent()} == expected


def test_validation_simulator_rejects_unknown_event(tmp_path: Path) -> None:
    client, journal = _client(tmp_path, enabled=True)

    response = client.post("/validation/events/PLACE_ORDER")

    assert response.status_code == 422
    assert journal.read_recent() == []
