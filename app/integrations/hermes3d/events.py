from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.auto_trading.state_store import AutoTradeStateStore
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.monitoring.position_store import PositionStore


class Hermes3DStateReader(Protocol):
    def state(self) -> dict[str, Any]: ...


class Hermes3DEventStream:
    """Read-only realtime stream for Hermes3D without exchange dependencies.

    Trading workers append normalized events to a local JSONL journal. The stream
    also observes position and auto-trading state files so an already-running
    legacy worker can still surface position close/open and circuit-breaker changes.
    No exchange client or order mutation method is used here.
    """

    def __init__(
        self,
        *,
        state_reader: Hermes3DStateReader,
        journal: Hermes3DEventJournal,
        spot_position_store: PositionStore,
        futures_position_store: PositionStore,
        auto_state_paths: dict[str, str | Path],
        interval_seconds: float = 0.25,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.state_reader = state_reader
        self.journal = journal
        self.spot_position_store = spot_position_store
        self.futures_position_store = futures_position_store
        self.auto_state_paths = {
            strategy_id: Path(path) for strategy_id, path in auto_state_paths.items()
        }
        self.interval_seconds = float(interval_seconds)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _snapshot_event(self) -> dict[str, Any]:
        return {
            "event": "STATE_SNAPSHOT",
            "agent_id": "market-data",
            "generated_at": self._now(),
            "payload": self.state_reader.state(),
        }

    def _active_positions(self) -> dict[str, dict[str, Any]]:
        rows = (
            self.spot_position_store.active_positions()
            + self.futures_position_store.active_positions()
        )
        return {
            str(item.get("order_id")): item
            for item in rows
            if item.get("order_id") is not None
        }

    def _closed_positions(self) -> dict[str, dict[str, Any]]:
        rows = self.spot_position_store.load() + self.futures_position_store.load()
        return {
            str(item.get("order_id")): item
            for item in rows
            if item.get("status") == "CLOSED" and item.get("order_id") is not None
        }

    def _halted_states(self) -> dict[str, dict[str, Any]]:
        halted: dict[str, dict[str, Any]] = {}
        for strategy_id, path in self.auto_state_paths.items():
            state = AutoTradeStateStore(path).load()
            if state.get("halted"):
                halted[strategy_id] = state
        return halted

    @staticmethod
    def _event_key(event: dict[str, Any]) -> str | None:
        event_name = str(event.get("event") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_name == "ORDER_OPEN":
            order_id = payload.get("order_id")
            return f"open:{order_id}" if order_id is not None else None
        if event_name in {"TP_HIT", "SL_HIT"}:
            order_id = payload.get("order_id")
            return f"closed:{order_id}:{event_name}" if order_id is not None else None
        if event_name == "CIRCUIT_BREAKER":
            strategy_id = payload.get("strategy_id")
            return f"halted:{strategy_id}" if strategy_id is not None else None
        return None

    def _initial_events(self) -> list[dict[str, Any]]:
        events = [self._snapshot_event()]
        for position in self._active_positions().values():
            events.append(
                {
                    "event": "ORDER_OPEN",
                    "agent_id": "positions",
                    "generated_at": self._now(),
                    "payload": position,
                }
            )
        for strategy_id, state in self._halted_states().items():
            events.append(
                {
                    "event": "CIRCUIT_BREAKER",
                    "agent_id": "risk-manager",
                    "generated_at": self._now(),
                    "payload": {
                        "strategy_id": strategy_id,
                        "reason": state.get("halt_reason"),
                        "halted_at": state.get("halted_at"),
                    },
                }
            )
        return events

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        offset = self.journal.size()
        active_ids = set(self._active_positions())
        closed_ids = set(self._closed_positions())
        halted_ids = set(self._halted_states())
        emitted_keys = {f"open:{order_id}" for order_id in active_ids}
        emitted_keys.update(f"halted:{strategy_id}" for strategy_id in halted_ids)

        for event in self._initial_events():
            yield event

        last_heartbeat = time.monotonic()
        while True:
            changed = False
            offset, records = self.journal.read_from(offset)
            for record in records:
                if record.get("event") == "STATE_CHANGED":
                    changed = True
                    continue
                key = self._event_key(record)
                if key is not None:
                    emitted_keys.add(key)
                yield record
                changed = True

            current_active = self._active_positions()
            current_active_ids = set(current_active)
            for order_id in sorted(current_active_ids - active_ids):
                key = f"open:{order_id}"
                if key not in emitted_keys:
                    event = {
                        "event": "ORDER_OPEN",
                        "agent_id": "positions",
                        "generated_at": self._now(),
                        "payload": current_active[order_id],
                    }
                    emitted_keys.add(key)
                    yield event
                    changed = True
            active_ids = current_active_ids

            current_closed = self._closed_positions()
            current_closed_ids = set(current_closed)
            for order_id in sorted(current_closed_ids - closed_ids):
                position = current_closed[order_id]
                reason = str(position.get("exit_reason") or "").upper()
                if reason not in {"TP_HIT", "SL_HIT"}:
                    continue
                key = f"closed:{order_id}:{reason}"
                if key not in emitted_keys:
                    event = {
                        "event": reason,
                        "agent_id": "positions",
                        "generated_at": self._now(),
                        "payload": position,
                    }
                    emitted_keys.add(key)
                    yield event
                    changed = True
            closed_ids = current_closed_ids

            current_halted = self._halted_states()
            current_halted_ids = set(current_halted)
            for strategy_id in sorted(current_halted_ids - halted_ids):
                key = f"halted:{strategy_id}"
                if key not in emitted_keys:
                    state = current_halted[strategy_id]
                    event = {
                        "event": "CIRCUIT_BREAKER",
                        "agent_id": "risk-manager",
                        "generated_at": self._now(),
                        "payload": {
                            "strategy_id": strategy_id,
                            "reason": state.get("halt_reason"),
                            "halted_at": state.get("halted_at"),
                        },
                    }
                    emitted_keys.add(key)
                    yield event
                    changed = True
            halted_ids = current_halted_ids

            if changed:
                yield self._snapshot_event()
                last_heartbeat = time.monotonic()
            elif time.monotonic() - last_heartbeat >= 15:
                yield {
                    "event": "HEARTBEAT",
                    "agent_id": "system",
                    "generated_at": self._now(),
                    "payload": {"read_only": True, "source": "local_state"},
                }
                last_heartbeat = time.monotonic()

            await asyncio.sleep(self.interval_seconds)
