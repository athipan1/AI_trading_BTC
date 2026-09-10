from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations.hermes3d.router import build_hermes3d_router


class _Reader:
    @staticmethod
    def registry() -> dict:
        return {"capabilities": ["trade_lifecycle"]}

    @staticmethod
    def state() -> dict:
        lifecycle = {
            "by_agent": {
                "triple_ema_short": {
                    "state": "STRATEGY_EVALUATING",
                    "event": "AGENT_ACTIVITY",
                }
            },
            "by_trade": {},
            "known_states": ["STRATEGY_EVALUATING"],
        }
        return {"lifecycle": lifecycle, "agent_statuses": {}}


def test_registry_is_static_and_state_exposes_trade_lifecycle_alias() -> None:
    app = FastAPI()
    app.include_router(build_hermes3d_router(_Reader()))
    client = TestClient(app)

    registry = client.get("/registry").json()
    assert "trade_lifecycle" in registry["capabilities"]
    assert "trade_lifecycle" not in registry

    state = client.get("/state").json()
    assert state["trade_lifecycle"] == state["lifecycle"]
    assert state["trade_lifecycle"]["by_agent"]["triple_ema_short"]["state"] == (
        "STRATEGY_EVALUATING"
    )
