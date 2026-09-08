from __future__ import annotations

from pathlib import Path

import pytest

from app.auto_trading.state_store import AutoTradeStateStore
from app.integrations.hermes3d.events import Hermes3DEventStream
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.projection import Hermes3DJournalStateProjection
from app.monitoring.position_store import PositionStore


def build_stream(tmp_path: Path) -> Hermes3DEventStream:
    spot = PositionStore(tmp_path / "spot.json")
    futures = PositionStore(tmp_path / "futures.json")
    journal = Hermes3DEventJournal(tmp_path / "events.jsonl")
    auto_state_paths = {
        "baseline": tmp_path / "baseline-auto.json",
        "triple_ema": tmp_path / "triple-auto.json",
        "triple_ema_short": tmp_path / "short-auto.json",
    }
    projection = Hermes3DJournalStateProjection(
        journal=journal,
        spot_position_store=spot,
        futures_position_store=futures,
        auto_state_paths=auto_state_paths,
        symbol="BTC/USDT",
        timeframe="1h",
    )
    return Hermes3DEventStream(
        state_reader=projection,
        journal=journal,
        spot_position_store=spot,
        futures_position_store=futures,
        auto_state_paths=auto_state_paths,
        interval_seconds=0.01,
    )


def test_initial_events_do_not_require_market_data(tmp_path: Path) -> None:
    stream = build_stream(tmp_path)

    events = stream._initial_events()

    assert events[0]["event"] == "STATE_SNAPSHOT"
    assert events[0]["payload"]["read_only"] is True
    assert events[0]["payload"]["degraded"] is True
    assert events[0]["payload"]["market"]["price"] is None


def test_initial_events_detect_open_position_and_circuit_breaker(tmp_path: Path) -> None:
    stream = build_stream(tmp_path)
    stream.spot_position_store.add_long_position(
        order_id="order-1",
        symbol="BTC/USDT",
        entry_price=12_000,
        quantity=0.001,
        take_profit=12_500,
        stop_loss=11_500,
    )
    AutoTradeStateStore(tmp_path / "baseline-auto.json").halt("max drawdown guard")

    names = {event["event"] for event in stream._initial_events()}

    assert "ORDER_OPEN" in names
    assert "CIRCUIT_BREAKER" in names


def test_event_journal_maps_trade_results(tmp_path: Path) -> None:
    journal = Hermes3DEventJournal(tmp_path / "events.jsonl")
    result = {
        "event": "BUY_FILLED",
        "strategy_id": "baseline",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "candle_ms": 123,
        "signal": {"action": "BUY"},
        "position": {
            "order_id": "123",
            "symbol": "BTC/USDT",
            "side": "buy",
            "entry_price": 80_000,
            "quantity": 0.001,
            "take_profit": 82_000,
            "stop_loss": 79_000,
        },
    }

    published = journal.publish_result(result)
    names = [event["event"] for event in published]

    assert names == [
        "AGENT_ACTIVITY",
        "BUY_READY",
        "AGENT_ACTIVITY",
        "AGENT_ACTIVITY",
        "RISK_PASS",
        "AGENT_ACTIVITY",
        "ORDER_OPEN",
        "STATE_CHANGED",
    ]
    activities = [event for event in published if event["event"] == "AGENT_ACTIVITY"]
    assert [(event["agent_id"], event["payload"]["activity"], event["payload"]["state"]) for event in activities] == [
        ("baseline", "strategy_evaluated", "SUCCESS"),
        ("risk-manager", "risk_check", "WORKING"),
        ("risk-manager", "risk_approved", "SUCCESS"),
        ("positions", "order_filled", "SUCCESS"),
    ]
    assert activities[1]["payload"]["speech"] == {
        "th": "กำลังตรวจ Risk",
        "en": "Checking risk",
    }
    assert activities[-1]["payload"]["message_key"] == "agent.execution.filled"

    offset, records = journal.read_from(0)
    assert offset == journal.size()
    assert [event["event"] for event in records] == names
    assert [event["event"] for event in journal.read_recent()] == names


def test_event_journal_activity_contract_rejects_unknown_state(tmp_path: Path) -> None:
    journal = Hermes3DEventJournal(tmp_path / "events.jsonl")

    with pytest.raises(ValueError, match="unsupported Hermes3D activity state"):
        journal.publish_activity(
            agent_id="baseline",
            activity="strategy_scan",
            state="DANCING",
            message_key="agent.strategy.scan",
            speech_th="กำลังตรวจสัญญาณ",
            speech_en="Checking signal",
        )


def test_event_journal_maps_risk_blocked_to_warning(tmp_path: Path) -> None:
    journal = Hermes3DEventJournal(tmp_path / "events.jsonl")
    published = journal.publish_result(
        {
            "event": "RISK_BLOCKED",
            "strategy_id": "baseline",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "signal": {"action": "BUY"},
            "risk": {"approved": False},
            "reason": "risk limit",
        }
    )

    risk_activities = [
        event for event in published if event["event"] == "AGENT_ACTIVITY" and event["agent_id"] == "risk-manager"
    ]
    assert [event["payload"]["state"] for event in risk_activities] == ["WORKING", "WARNING"]
    assert risk_activities[-1]["payload"]["activity"] == "risk_blocked"
    assert risk_activities[-1]["payload"]["speech"]["th"] == "Risk ไม่ผ่าน"


def test_event_journal_maps_tp_and_circuit_breaker(tmp_path: Path) -> None:
    journal = Hermes3DEventJournal(tmp_path / "events.jsonl")
    result = {
        "event": "POSITION_CLOSED",
        "strategy_id": "baseline",
        "reason": "TP_HIT",
        "symbol": "BTC/USDT",
        "closed_position": {
            "order_id": "123",
            "exit_order_id": "456",
            "symbol": "BTC/USDT",
            "entry_price": 80_000,
            "exit_price": 82_000,
        },
    }

    journal.publish_result(result)
    journal.publish_circuit_breaker(strategy_id="baseline", reason="max drawdown")
    _, records = journal.read_from(0)
    names = [event["event"] for event in records]

    assert "TP_HIT" in names
    assert "CIRCUIT_BREAKER" in names
    activities = [event for event in records if event["event"] == "AGENT_ACTIVITY"]
    assert any(event["payload"]["activity"] == "position_closed" for event in activities)
    halt = [event for event in activities if event["payload"]["activity"] == "circuit_breaker"][-1]
    assert halt["payload"]["state"] == "ERROR"
