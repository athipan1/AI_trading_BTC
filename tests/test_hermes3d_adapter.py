from __future__ import annotations

from pathlib import Path

import pytest

from app.execution.paper import PaperBroker
from app.integrations.hermes3d.adapter import Hermes3DReadOnlyAdapter
from app.models import Candle
from app.monitoring.position_store import PositionStore
from app.risk.engine import RiskEngine


class FakeMarketData:
    def __init__(self, candle_count: int = 250) -> None:
        self.candle_count = candle_count

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 250) -> list[Candle]:
        count = min(self.candle_count, limit)
        return [
            Candle(
                timestamp_ms=(index + 1) * 3_600_000,
                open=10_000 + index * 10,
                high=10_020 + index * 10,
                low=9_980 + index * 10,
                close=10_010 + index * 10,
                volume=100 + index,
            )
            for index in range(count)
        ]


def build_adapter(tmp_path: Path, candle_count: int = 250) -> Hermes3DReadOnlyAdapter:
    return Hermes3DReadOnlyAdapter(
        market_data=FakeMarketData(candle_count),
        risk_engine=RiskEngine(),
        paper_broker=PaperBroker(10_000),
        spot_position_store=PositionStore(tmp_path / "spot.json"),
        futures_position_store=PositionStore(tmp_path / "futures.json"),
        symbol="BTC/USDT",
        timeframe="1h",
        market_data_limit=250,
    )


def test_registry_declares_read_only_capabilities() -> None:
    registry = Hermes3DReadOnlyAdapter.registry()

    assert registry["mode"] == "read_only"
    assert registry["trade_execution"] is False
    assert set(registry["capabilities"]) == {"market_state", "strategies", "risk", "positions"}
    assert "readonly-observer" in registry["models"]
    assert {agent["id"] for agent in registry["agents"]} == {
        "market-data",
        "baseline",
        "triple_ema",
        "triple_ema_short",
        "risk-manager",
        "positions",
    }


def test_state_exposes_market_strategies_risk_and_positions(tmp_path: Path) -> None:
    adapter = build_adapter(tmp_path)
    adapter.spot_position_store.add_long_position(
        order_id="123",
        symbol="BTC/USDT",
        entry_price=12_000,
        quantity=0.001,
        take_profit=12_500,
        stop_loss=11_500,
    )

    state = adapter.state()

    assert state["read_only"] is True
    assert state["permissions"]["trade_execution"] is False
    assert state["permissions"]["order_cancel"] is False
    assert state["permissions"]["position_modify"] is False
    assert state["runtime"]["name"] == "AI Trading BTC"
    assert state["runtime"]["status"] == "read_only"
    assert state["profileName"] == "btc-trading-room"
    assert set(state["active"]) == {
        "market-data",
        "baseline",
        "triple_ema",
        "triple_ema_short",
        "risk-manager",
        "positions",
    }
    assert set(state["agent_statuses"]) == set(state["active"])
    assert state["agent_statuses"]["market-data"]["status"] == "OBSERVING"
    assert state["agent_statuses"]["positions"]["status"] == "OPEN"
    assert state["market"]["symbol"] == "BTC/USDT"
    assert {item["strategy_id"] for item in state["strategies"]} == {
        "baseline",
        "triple_ema",
        "triple_ema_short",
    }
    assert state["risk"]["execution_enabled"] is False
    assert len(state["positions"]["spot_testnet"]) == 1
    assert state["positions"]["futures_testnet_short"] == []


def test_state_requires_enough_history_for_all_strategies(tmp_path: Path) -> None:
    adapter = build_adapter(tmp_path, candle_count=200)

    with pytest.raises(ValueError, match="at least 201 candles"):
        adapter.state()
