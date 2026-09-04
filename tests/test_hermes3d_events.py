from __future__ import annotations

from pathlib import Path

from app.auto_trading.state_store import AutoTradeStateStore
from app.execution.paper import PaperBroker
from app.integrations.hermes3d.adapter import Hermes3DReadOnlyAdapter
from app.integrations.hermes3d.events import Hermes3DEventStream
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.models import Candle
from app.monitoring.position_store import PositionStore
from app.risk.engine import RiskEngine


class RisingMarketData:
    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 250) -> list[Candle]:
        return [
            Candle(
                timestamp_ms=(index + 1) * 3_600_000,
                open=10_000 + index * 20,
                high=10_030 + index * 20,
                low=9_990 + index * 20,
                close=10_020 + index * 20,
                volume=100 + index,
            )
            for index in range(limit)
        ]


def build_stream(tmp_path: Path) -> Hermes3DEventStream:
    spot = PositionStore(tmp_path / "spot.json")
    futures = PositionStore(tmp_path / "futures.json")
    adapter = Hermes3DReadOnlyAdapter(
        market_data=RisingMarketData(),
        risk_engine=RiskEngine(),
        paper_broker=PaperBroker(10_000),
        spot_position_store=spot,
        futures_position_store=futures,
        symbol="BTC/USDT",
        timeframe="1h",
        market_data_limit=250,
    )
    return Hermes3DEventStream(
        adapter=adapter,
        journal=Hermes3DEventJournal(tmp_path / "events.jsonl"),
        spot_position_store=spot,
        futures_position_store=futures,
        auto_state_paths={
            "baseline": tmp_path / "baseline-auto.json",
            "triple_ema": tmp_path / "triple-auto.json",
            "triple_ema_short": tmp_path / "short-auto.json",
        },
        interval_seconds=0.01,
    )


def test_initial_events_include_snapshot_ready_and_risk_pass(tmp_path: Path) -> None:
    stream = build_stream(tmp_path)

    names = {event["event"] for event in stream._initial_events()}

    assert "STATE_SNAPSHOT" in names
    assert "BUY_READY" in names
    assert "RISK_PASS" in names


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

    assert names == ["BUY_READY", "RISK_PASS", "ORDER_OPEN", "STATE_CHANGED"]
    offset, records = journal.read_from(0)
    assert offset == journal.size()
    assert [event["event"] for event in records] == names


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
