from __future__ import annotations

import json
from pathlib import Path

from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.sidecar import (
    Hermes3DLegacyLogSidecar,
    Hermes3DSidecarCursorStore,
    LogSource,
)


def test_persisted_zero_cursor_is_normalized_to_eof_on_restart(tmp_path: Path) -> None:
    source = tmp_path / "spot-long.log"
    cursor_path = tmp_path / "cursors.json"
    journal_path = tmp_path / "events.jsonl"

    source.write_text(
        json.dumps(
            {
                "event": "BUY_FILLED",
                "strategy_id": "baseline",
                "signal": {"action": "BUY"},
                "position": {"order_id": "historical-order", "symbol": "BTC/USDT"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cursor_path.write_text(
        json.dumps({"spot": {"inode": 0, "offset": 0}}),
        encoding="utf-8",
    )

    sidecar = Hermes3DLegacyLogSidecar(
        sources=[LogSource("spot", source)],
        journal=Hermes3DEventJournal(journal_path),
        cursor_store=Hermes3DSidecarCursorStore(cursor_path),
        start_at_end=True,
    )

    cursor = sidecar.cursors["spot"]
    assert cursor["inode"] == source.stat().st_ino
    assert cursor["offset"] == source.stat().st_size
    assert json.loads(cursor_path.read_text(encoding="utf-8"))["spot"] == cursor
    assert sidecar.poll_once() == {"lines": 0, "events": 0}
    assert sidecar.journal.read_from(0)[1] == []
