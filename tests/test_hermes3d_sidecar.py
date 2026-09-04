from __future__ import annotations

import json
from pathlib import Path

from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.sidecar import (
    Hermes3DLegacyLogSidecar,
    Hermes3DSidecarCursorStore,
    LogSource,
)


def _append(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _build(tmp_path: Path, *, start_at_end: bool = True) -> Hermes3DLegacyLogSidecar:
    spot = tmp_path / "spot.log"
    futures = tmp_path / "futures.log"
    spot.touch()
    futures.touch()
    return Hermes3DLegacyLogSidecar(
        sources=[LogSource("spot", spot), LogSource("futures", futures)],
        journal=Hermes3DEventJournal(tmp_path / "events.jsonl"),
        cursor_store=Hermes3DSidecarCursorStore(tmp_path / "cursors.json"),
        start_at_end=start_at_end,
    )


def test_sidecar_starts_at_eof_and_only_publishes_new_signal(tmp_path: Path) -> None:
    spot = tmp_path / "spot.log"
    futures = tmp_path / "futures.log"
    spot.write_text(json.dumps({"event": "OLD", "signal": {"action": "BUY"}}) + "\n")
    futures.touch()
    journal = Hermes3DEventJournal(tmp_path / "events.jsonl")
    sidecar = Hermes3DLegacyLogSidecar(
        sources=[LogSource("spot", spot), LogSource("futures", futures)],
        journal=journal,
        cursor_store=Hermes3DSidecarCursorStore(tmp_path / "cursors.json"),
        start_at_end=True,
    )

    assert sidecar.poll_once() == {"lines": 0, "events": 0}
    _append(
        spot,
        {
            "event": "BUY_READY_CHECK",
            "strategy_id": "baseline",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "signal": {"action": "BUY", "regime": "BULL_TREND"},
            "risk": {"approved": True},
        },
    )

    result = sidecar.poll_once()
    assert result["lines"] == 1
    _, records = journal.read_from(0)
    names = [record["event"] for record in records]
    assert names == ["BUY_READY", "RISK_PASS", "STATE_CHANGED"]


def test_sidecar_maps_position_close_and_halt(tmp_path: Path) -> None:
    sidecar = _build(tmp_path, start_at_end=False)
    spot = tmp_path / "spot.log"
    futures = tmp_path / "futures.log"
    _append(
        spot,
        {
            "event": "POSITION_CLOSED",
            "strategy_id": "baseline",
            "reason": "SL_HIT",
            "symbol": "BTC/USDT",
            "closed_position": {
                "order_id": "1",
                "exit_order_id": "2",
                "symbol": "BTC/USDT",
                "entry_price": 80000,
                "exit_price": 79000,
            },
        },
    )
    _append(
        futures,
        {
            "event": "FUTURES_SHORT_HALTED",
            "strategy_id": "triple_ema_short",
            "reason": "max drawdown guard",
        },
    )

    sidecar.poll_once()
    _, records = sidecar.journal.read_from(0)
    names = [record["event"] for record in records]
    assert "SL_HIT" in names
    assert "CIRCUIT_BREAKER" in names


def test_sidecar_cursor_prevents_duplicate_replay_after_restart(tmp_path: Path) -> None:
    spot = tmp_path / "spot.log"
    futures = tmp_path / "futures.log"
    spot.touch()
    futures.touch()
    journal = Hermes3DEventJournal(tmp_path / "events.jsonl")
    cursor_store = Hermes3DSidecarCursorStore(tmp_path / "cursors.json")
    first = Hermes3DLegacyLogSidecar(
        sources=[LogSource("spot", spot), LogSource("futures", futures)],
        journal=journal,
        cursor_store=cursor_store,
        start_at_end=True,
    )
    _append(
        futures,
        {
            "event": "SHORT_FILLED",
            "strategy_id": "triple_ema_short",
            "signal": {"action": "SHORT"},
            "position": {
                "order_id": "9",
                "symbol": "BTC/USDT",
                "side": "sell",
                "entry_price": 80000,
                "quantity": 0.001,
                "take_profit": 78000,
                "stop_loss": 81000,
            },
        },
    )
    first.poll_once()
    before = len(journal.read_from(0)[1])

    restarted = Hermes3DLegacyLogSidecar(
        sources=[LogSource("spot", spot), LogSource("futures", futures)],
        journal=journal,
        cursor_store=cursor_store,
        start_at_end=True,
    )
    assert restarted.poll_once() == {"lines": 0, "events": 0}
    assert len(journal.read_from(0)[1]) == before
