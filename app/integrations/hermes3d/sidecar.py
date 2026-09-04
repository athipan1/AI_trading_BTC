from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.integrations.hermes3d.journal import Hermes3DEventJournal


@dataclass(frozen=True)
class LogSource:
    source_id: str
    path: Path


class Hermes3DSidecarCursorStore:
    """Persist byte offsets so the observer can restart without replaying old logs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, dict[str, int]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("sidecar cursor store must contain a JSON object")
        result: dict[str, dict[str, int]] = {}
        for key, value in payload.items():
            if not isinstance(value, dict):
                continue
            result[str(key)] = {
                "offset": max(0, int(value.get("offset", 0))),
                "inode": max(0, int(value.get("inode", 0))),
            }
        return result

    def save(self, cursors: dict[str, dict[str, int]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(cursors, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, self.path)


class Hermes3DLegacyLogSidecar:
    """Read-only bridge from already-running trader stdout logs to Hermes3D events.

    The sidecar never imports an exchange broker, never reads API credentials, and
    never mutates trader state. It tails JSON lines already emitted by the legacy
    workers and republishes only normalized observability events.
    """

    HALT_EVENTS = {"AUTO_TRADING_HALTED", "FUTURES_SHORT_HALTED"}
    TRADE_EVENTS = {"BUY_FILLED", "SHORT_FILLED", "POSITION_CLOSED", "SHORT_CLOSED"}

    def __init__(
        self,
        *,
        sources: list[LogSource],
        journal: Hermes3DEventJournal,
        cursor_store: Hermes3DSidecarCursorStore,
        start_at_end: bool = True,
    ) -> None:
        if not sources:
            raise ValueError("at least one log source is required")
        self.sources = sources
        self.journal = journal
        self.cursor_store = cursor_store
        self.start_at_end = start_at_end
        self.cursors = cursor_store.load()
        self._initialize_missing_cursors()

    def _initialize_missing_cursors(self) -> None:
        changed = False
        for source in self.sources:
            if source.source_id in self.cursors:
                continue
            try:
                stat = source.path.stat()
            except FileNotFoundError:
                self.cursors[source.source_id] = {"offset": 0, "inode": 0}
            else:
                self.cursors[source.source_id] = {
                    "offset": stat.st_size if self.start_at_end else 0,
                    "inode": int(stat.st_ino),
                }
            changed = True
        if changed:
            self.cursor_store.save(self.cursors)

    @staticmethod
    def _parse_json_line(raw: bytes) -> dict[str, Any] | None:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _has_entry_signal(payload: dict[str, Any]) -> bool:
        signal = payload.get("signal")
        return isinstance(signal, dict) and str(signal.get("action")) in {"BUY", "SHORT"}

    def _publish_payload(self, payload: dict[str, Any]) -> int:
        event_name = str(payload.get("event") or "")
        if event_name in self.HALT_EVENTS:
            state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
            strategy_id = str(payload.get("strategy_id") or "unknown")
            reason = str(payload.get("reason") or state.get("halt_reason") or "trading halted")
            self.journal.publish_circuit_breaker(strategy_id=strategy_id, reason=reason)
            return 1
        if event_name in self.TRADE_EVENTS or self._has_entry_signal(payload):
            return len(self.journal.publish_result(payload))
        return 0

    def _read_source(self, source: LogSource) -> tuple[int, int]:
        cursor = self.cursors[source.source_id]
        try:
            stat = source.path.stat()
        except FileNotFoundError:
            return 0, 0

        inode = int(stat.st_ino)
        offset = int(cursor.get("offset", 0))
        previous_inode = int(cursor.get("inode", 0))
        if previous_inode not in {0, inode} or stat.st_size < offset:
            offset = 0

        parsed = 0
        published = 0
        with source.path.open("rb") as handle:
            handle.seek(offset)
            while True:
                start = handle.tell()
                raw = handle.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    handle.seek(start)
                    break
                parsed += 1
                payload = self._parse_json_line(raw)
                if payload is not None:
                    published += self._publish_payload(payload)
                offset = handle.tell()

        self.cursors[source.source_id] = {"offset": offset, "inode": inode}
        return parsed, published

    def poll_once(self) -> dict[str, int]:
        lines = 0
        events = 0
        for source in self.sources:
            parsed, published = self._read_source(source)
            lines += parsed
            events += published
        self.cursor_store.save(self.cursors)
        return {"lines": lines, "events": events}

    def run_forever(self, interval_seconds: float = 1.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        while True:
            self.poll_once()
            time.sleep(interval_seconds)
