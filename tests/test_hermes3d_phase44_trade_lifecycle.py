from __future__ import annotations

from datetime import UTC, datetime

from app.integrations.hermes3d.lifecycle import (
    correlation_from_event,
    lifecycle_snapshot,
    lifecycle_state_from_event,
)


def event(name: str, agent_id: str, payload: dict) -> dict:
    return {
        "event": name,
        "agent_id": agent_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


def test_maps_existing_wire_events_without_breaking_legacy_contract() -> None:
    assert lifecycle_state_from_event(event("BUY_READY", "baseline", {})) == "SIGNAL_DETECTED"
    assert lifecycle_state_from_event(event("SHORT_READY", "triple_ema_short", {})) == "SIGNAL_DETECTED"
    assert lifecycle_state_from_event(event("RISK_PASS", "risk-manager", {})) == "RISK_APPROVED"
    assert lifecycle_state_from_event(event("ORDER_OPEN", "positions", {})) == "ORDER_OPENED"
    assert lifecycle_state_from_event(event("TP_HIT", "positions", {})) == "POSITION_CLOSED"
    assert lifecycle_state_from_event(event("SL_HIT", "positions", {})) == "POSITION_CLOSED"
    assert lifecycle_state_from_event(event("CIRCUIT_BREAKER", "risk-manager", {})) == "HALTED"


def test_maps_agent_activity_into_operational_lifecycle() -> None:
    cases = {
        "strategy_check": "STRATEGY_EVALUATING",
        "risk_check": "RISK_CHECKING",
        "risk_blocked": "RISK_REJECTED",
        "risk_approved": "RISK_APPROVED",
        "order_filled_sync": "RECONCILING",
        "order_filled": "POSITION_ACTIVE",
        "position_closed_sync": "RECONCILING",
        "position_closed": "POSITION_CLOSED",
        "circuit_breaker": "HALTED",
    }
    for activity, expected in cases.items():
        record = event("AGENT_ACTIVITY", "positions", {"activity": activity})
        assert lifecycle_state_from_event(record) == expected


def test_correlation_uses_strategy_and_order_as_stable_trade_id() -> None:
    record = event(
        "ORDER_OPEN",
        "positions",
        {
            "strategy_id": "triple_ema",
            "symbol": "BTC/USDT",
            "order_id": 12345,
        },
    )
    correlation = correlation_from_event(record)
    assert correlation.strategy_id == "triple_ema"
    assert correlation.symbol == "BTC/USDT"
    assert correlation.order_id == "12345"
    assert correlation.trade_id == "triple_ema:12345"


def test_lifecycle_snapshot_tracks_latest_agent_and_trade_state() -> None:
    records = [
        event(
            "BUY_READY",
            "baseline",
            {"strategy_id": "baseline", "symbol": "BTC/USDT"},
        ),
        event(
            "ORDER_OPEN",
            "positions",
            {
                "strategy_id": "baseline",
                "symbol": "BTC/USDT",
                "order_id": "order-1",
            },
        ),
        event(
            "AGENT_ACTIVITY",
            "positions",
            {
                "activity": "order_filled",
                "strategy_id": "baseline",
                "symbol": "BTC/USDT",
                "order_id": "order-1",
            },
        ),
    ]

    snapshot = lifecycle_snapshot(records)

    assert snapshot["by_agent"]["baseline"]["state"] == "SIGNAL_DETECTED"
    assert snapshot["by_agent"]["positions"]["state"] == "POSITION_ACTIVE"
    assert snapshot["by_trade"]["baseline:order-1"]["state"] == "POSITION_ACTIVE"


def test_risk_rejection_never_looks_like_order_opened() -> None:
    records = [
        event(
            "BUY_READY",
            "baseline",
            {"strategy_id": "baseline", "symbol": "BTC/USDT"},
        ),
        event(
            "AGENT_ACTIVITY",
            "risk-manager",
            {
                "activity": "risk_check",
                "strategy_id": "baseline",
                "symbol": "BTC/USDT",
            },
        ),
        event(
            "AGENT_ACTIVITY",
            "risk-manager",
            {
                "activity": "risk_blocked",
                "strategy_id": "baseline",
                "symbol": "BTC/USDT",
                "reason": "risk limit",
            },
        ),
    ]

    snapshot = lifecycle_snapshot(records)

    assert snapshot["by_agent"]["risk-manager"]["state"] == "RISK_REJECTED"
    assert all(item["state"] != "ORDER_OPENED" for item in snapshot["by_agent"].values())
