from __future__ import annotations

import json
from pathlib import Path

from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.production_projection import (
    Hermes3DProductionJournalStateProjection,
)
from app.monitoring.position_store import PositionStore


def build_projection(tmp_path: Path) -> Hermes3DProductionJournalStateProjection:
    return Hermes3DProductionJournalStateProjection(
        journal=Hermes3DEventJournal(tmp_path / "events.jsonl"),
        spot_position_store=PositionStore(tmp_path / "spot.json"),
        futures_position_store=PositionStore(tmp_path / "futures.json"),
        auto_state_paths={
            "baseline": tmp_path / "baseline-auto.json",
            "triple_ema": tmp_path / "triple-auto.json",
            "triple_ema_short": tmp_path / "short-auto.json",
        },
        symbol="BTC/USDT",
        timeframe="1h",
    )


def test_production_projection_ignores_live_office_validation_events(tmp_path: Path) -> None:
    projection = build_projection(tmp_path)
    projection.journal.publish(
        event="BUY_READY",
        agent_id="triple_ema",
        payload={
            "strategy_id": "triple_ema",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "signal": {"action": "BUY", "regime": "BULL_TREND"},
            "diagnostic": {"price": 81_000.0, "ema20": 80_500.0},
        },
    )
    projection.journal.publish(
        event="BUY_READY",
        agent_id="triple_ema",
        payload={
            "strategy_id": "triple_ema",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "validation": True,
            "read_only": True,
            "source": "phase-1.7.2-live-office-validation",
            "signal": {"action": "BUY", "validation": True},
            "diagnostic": {"price": 1.0},
        },
    )
    projection.journal.publish(
        event="ORDER_OPEN",
        agent_id="positions",
        payload={
            "strategy_id": "triple_ema",
            "validation": True,
            "read_only": True,
            "source": "phase-1.7.2-live-office-validation",
            "order_id": "phase17-validation-123",
            "symbol": "BTC/USDT",
        },
    )

    state = projection.state()
    triple_ema = next(
        item for item in state["strategies"] if item["strategy_id"] == "triple_ema"
    )
    encoded = json.dumps(state)

    assert triple_ema["signal"] == {"action": "BUY", "regime": "BULL_TREND"}
    assert state["market"]["price"] == 81_000.0
    assert '"validation": true' not in encoded
    assert "phase17-validation" not in encoded
    assert "phase-1.7.2-live-office-validation" not in encoded


def test_production_projection_keeps_validation_records_in_journal_for_audit(
    tmp_path: Path,
) -> None:
    projection = build_projection(tmp_path)
    projection.journal.publish(
        event="RISK_PASS",
        agent_id="risk-manager",
        payload={
            "strategy_id": "triple_ema",
            "validation": True,
            "source": "phase-1.7.2-live-office-validation",
            "risk": {"approved": True},
        },
    )

    state = projection.state()
    records = projection.journal.read_recent()

    assert len(records) == 1
    assert records[0]["payload"]["validation"] is True
    triple_ema = next(
        item for item in state["strategies"] if item["strategy_id"] == "triple_ema"
    )
    assert triple_ema["risk"]["approved"] is False
