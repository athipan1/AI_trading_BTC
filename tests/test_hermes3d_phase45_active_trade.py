from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations.hermes3d.lifecycle import lifecycle_snapshot
from app.integrations.hermes3d.router import build_hermes3d_router


def _record(
    event: str,
    *,
    agent_id: str,
    generated_at: str,
    payload: dict,
) -> dict:
    return {
        "event": event,
        "agent_id": agent_id,
        "generated_at": generated_at,
        "payload": payload,
    }


def test_active_trade_prefers_open_trade_over_new_unrelated_risk_rejection() -> None:
    records = [
        _record(
            "ORDER_OPEN",
            agent_id="positions",
            generated_at="2026-09-10T10:00:00+00:00",
            payload={
                "strategy_id": "triple_ema_short",
                "symbol": "BTC/USDT",
                "order_id": "trade-a",
            },
        ),
        _record(
            "AGENT_ACTIVITY",
            agent_id="risk-manager",
            generated_at="2026-09-10T10:05:00+00:00",
            payload={
                "activity": "risk_blocked",
                "strategy_id": "triple_ema_short",
                "symbol": "BTC/USDT",
            },
        ),
    ]

    snapshot = lifecycle_snapshot(records)

    assert snapshot["by_agent"]["risk-manager"]["state"] == "RISK_REJECTED"
    assert snapshot["active_trade"]["state"] == "ORDER_OPENED"
    assert snapshot["active_trade"]["correlation"]["trade_id"] == (
        "triple_ema_short:trade-a"
    )


def test_trade_history_is_scoped_and_terminal_trade_is_not_active() -> None:
    records = [
        _record(
            "ORDER_OPEN",
            agent_id="positions",
            generated_at="2026-09-10T10:00:00+00:00",
            payload={"strategy_id": "baseline", "symbol": "BTC/USDT", "order_id": "1"},
        ),
        _record(
            "AGENT_ACTIVITY",
            agent_id="positions",
            generated_at="2026-09-10T10:01:00+00:00",
            payload={
                "activity": "order_filled",
                "strategy_id": "baseline",
                "symbol": "BTC/USDT",
                "order_id": "1",
            },
        ),
        _record(
            "TP_HIT",
            agent_id="positions",
            generated_at="2026-09-10T10:10:00+00:00",
            payload={"strategy_id": "baseline", "symbol": "BTC/USDT", "order_id": "1"},
        ),
    ]

    snapshot = lifecycle_snapshot(records)
    trade = snapshot["by_trade"]["baseline:1"]

    assert [item["state"] for item in trade["history"]] == [
        "ORDER_OPENED",
        "POSITION_ACTIVE",
        "POSITION_CLOSED",
    ]
    assert trade["terminal"] is True
    assert snapshot["active_trade"] is None


class _Reader:
    @staticmethod
    def registry() -> dict:
        return {"capabilities": ["trade_lifecycle"]}

    @staticmethod
    def state() -> dict:
        lifecycle = lifecycle_snapshot(
            [
                _record(
                    "ORDER_OPEN",
                    agent_id="positions",
                    generated_at="2026-09-10T10:00:00+00:00",
                    payload={
                        "strategy_id": "triple_ema_short",
                        "symbol": "BTC/USDT",
                        "order_id": "9",
                    },
                )
            ]
        )
        return {"lifecycle": lifecycle, "agent_statuses": {}}


def test_state_exposes_active_trade_and_trade_lifecycles() -> None:
    app = FastAPI()
    app.include_router(build_hermes3d_router(_Reader()))
    state = TestClient(app).get("/state").json()

    assert state["trade_lifecycle"] == state["lifecycle"]
    assert state["active_trade"]["correlation"]["trade_id"] == "triple_ema_short:9"
    assert "triple_ema_short:9" in state["trade_lifecycles"]
