from __future__ import annotations

from pathlib import Path

from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.projection import Hermes3DJournalStateProjection
from app.monitoring.position_store import PositionStore


def build_projection(tmp_path: Path) -> Hermes3DJournalStateProjection:
    return Hermes3DJournalStateProjection(
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


def test_projection_exposes_signal_and_risk_lifecycle(tmp_path: Path) -> None:
    projection = build_projection(tmp_path)
    projection.journal.publish(
        event="BUY_READY",
        agent_id="baseline",
        payload={
            "strategy_id": "baseline",
            "symbol": "BTC/USDT",
            "signal": {"action": "BUY"},
        },
    )
    projection.journal.publish_activity(
        agent_id="risk-manager",
        activity="risk_check",
        state="WORKING",
        message_key="agent.risk.checking",
        speech_th="กำลังตรวจ Risk",
        speech_en="Checking risk",
        context={"strategy_id": "baseline", "symbol": "BTC/USDT"},
    )

    state = projection.state()

    assert state["agent_statuses"]["baseline"]["lifecycle"]["state"] == "SIGNAL_DETECTED"
    assert state["agent_statuses"]["risk-manager"]["lifecycle"]["state"] == "RISK_CHECKING"
    assert state["lifecycle"]["by_agent"]["baseline"]["state"] == "SIGNAL_DETECTED"


def test_projection_exposes_correlated_position_lifecycle(tmp_path: Path) -> None:
    projection = build_projection(tmp_path)
    projection.journal.publish(
        event="ORDER_OPEN",
        agent_id="positions",
        payload={
            "strategy_id": "triple_ema_short",
            "order_id": "order-42",
            "symbol": "BTC/USDT",
        },
    )

    state = projection.state()
    lifecycle = state["agent_statuses"]["positions"]["lifecycle"]

    assert lifecycle["state"] == "ORDER_OPENED"
    assert lifecycle["correlation"] == {
        "strategy_id": "triple_ema_short",
        "symbol": "BTC/USDT",
        "order_id": "order-42",
        "trade_id": "triple_ema_short:order-42",
    }
    assert state["lifecycle"]["by_trade"]["triple_ema_short:order-42"]["state"] == "ORDER_OPENED"


def test_registry_advertises_trade_lifecycle_capability(tmp_path: Path) -> None:
    projection = build_projection(tmp_path)

    registry = projection.registry()

    assert "trade_lifecycle" in registry["capabilities"]
