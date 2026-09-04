from __future__ import annotations

from pathlib import Path

from app.auto_trading.state_store import AutoTradeStateStore
from app.execution.paper import PaperBroker
from app.integrations.hermes3d.adapter import Hermes3DReadOnlyAdapter
from app.integrations.hermes3d.events import Hermes3DEventStream
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
        spot_position_store=spot,
        futures_position_store=futures,
        auto_state_paths={
            "baseline": tmp_path / "baseline-auto.json",
            "triple_ema": tmp_path / "triple-auto.json",
            "triple_ema_short": tmp_path / "short-auto.json",
        },
        interval_seconds=0.01,
    )


def test_snapshot_events_include_ready_and_risk_pass(tmp_path: Path) -> None:
    stream = build_stream(tmp_path)

    events = stream.snapshot_events()
    names = {event.event for event in events.values()}

    assert "STATE_SNAPSHOT" in names
    assert "BUY_READY" in names
    assert "RISK_PASS" in names


def test_snapshot_events_detect_order_tp_and_circuit_breaker(tmp_path: Path) -> None:
    stream = build_stream(tmp_path)
    position = stream.spot_position_store.add_long_position(
        order_id="order-1",
        symbol="BTC/USDT",
        entry_price=12_000,
        quantity=0.001,
        take_profit=12_500,
        stop_loss=11_500,
    )

    open_events = stream.snapshot_events()
    assert any(event.event == "ORDER_OPEN" for event in open_events.values())

    stream.spot_position_store.mark_closed(
        str(position["order_id"]),
        exit_order_id="exit-1",
        exit_reason="TP_HIT",
        exit_price=12_500,
    )
    AutoTradeStateStore(tmp_path / "baseline-auto.json").halt("max drawdown guard")

    closed_events = stream.snapshot_events()
    names = {event.event for event in closed_events.values()}
    assert "TP_HIT" in names
    assert "CIRCUIT_BREAKER" in names
