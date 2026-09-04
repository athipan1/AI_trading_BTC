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


def test_projection_is_healthy_without_journal_or_ccxt(tmp_path: Path) -> None:
    projection = build_projection(tmp_path)

    state = projection.state()

    assert state["read_only"] is True
    assert state["degraded"] is True
    assert state["source"] == "hermes3d_event_journal"
    assert state["market"]["symbol"] == "BTC/USDT"
    assert state["market"]["price"] is None
    assert state["permissions"]["trade_execution"] is False
    assert state["agent_statuses"]["market-data"]["status"] == "WAITING_FOR_PRODUCER"


def test_projection_reconstructs_market_strategy_and_risk(tmp_path: Path) -> None:
    projection = build_projection(tmp_path)
    projection.journal.publish(
        event="BUY_READY",
        agent_id="baseline",
        payload={
            "strategy_id": "baseline",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "candle_ms": 123,
            "signal": {"action": "BUY", "regime": "BULL_TREND", "reasons": ["ready"]},
            "diagnostic": {
                "price": 80_000,
                "ema_fast": 79_500,
                "ema_slow": 79_000,
                "rsi": 62.5,
                "momentum_pct": 0.4,
                "atr": 1_200,
            },
        },
    )
    projection.journal.publish(
        event="RISK_PASS",
        agent_id="risk-manager",
        payload={
            "strategy_id": "baseline",
            "signal_action": "BUY",
            "risk": {"approved": True, "reason": "approved"},
        },
    )

    state = projection.state()

    assert state["degraded"] is False
    assert state["market"]["price"] == 80_000
    assert state["market"]["ema20"] == 79_500
    assert state["market"]["ema50"] == 79_000
    assert state["market"]["regime"] == "BULL_TREND"
    assert state["risk"]["entry_signals"] == 1
    assert state["risk"]["approved_entries"] == 1
    baseline = next(item for item in state["strategies"] if item["strategy_id"] == "baseline")
    assert baseline["signal"]["action"] == "BUY"
    assert baseline["risk"]["approved"] is True
