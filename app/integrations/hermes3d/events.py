from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator

from app.auto_trading.state_store import AutoTradeStateStore
from app.integrations.hermes3d.adapter import Hermes3DReadOnlyAdapter
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.monitoring.position_store import PositionStore


class Hermes3DEventStream:
    """Read-only realtime stream for Hermes3D.

    Trading workers append normalized events to a local JSONL journal. This reader
    tails that journal and emits SSE/WebSocket messages without exposing any order
    mutation method. A fresh state snapshot is emitted after each event batch.
    """

    def __init__(
        self,
        *,
        adapter: Hermes3DReadOnlyAdapter,
        journal: Hermes3DEventJournal,
        spot_position_store: PositionStore,
        futures_position_store: PositionStore,
        auto_state_paths: dict[str, str | Path],
        interval_seconds: float = 0.25,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.adapter = adapter
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
            "payload": self.adapter.state(),
        }

    def _initial_events(self) -> list[dict[str, Any]]:
        state = self.adapter.state()
        events: list[dict[str, Any]] = [
            {
                "event": "STATE_SNAPSHOT",
                "agent_id": "market-data",
                "generated_at": self._now(),
                "payload": state,
            }
        ]

        for item in state.get("strategies", []):
            signal = item.get("signal") or {}
            risk = item.get("risk") or {}
            action = str(signal.get("action", "HOLD"))
            strategy_id = str(item.get("strategy_id", "unknown"))
            if action in {"BUY", "SHORT"}:
                events.append(
                    {
                        "event": "BUY_READY" if action == "BUY" else "SHORT_READY",
                        "agent_id": strategy_id,
                        "generated_at": self._now(),
                        "payload": {
                            "strategy_id": strategy_id,
                            "signal": signal,
                            "diagnostic": item.get("diagnostic") or {},
                        },
                    }
                )
                if bool(risk.get("approved")):
                    events.append(
                        {
                            "event": "RISK_PASS",
                            "agent_id": "risk-manager",
                            "generated_at": self._now(),
                            "payload": {
                                "strategy_id": strategy_id,
                                "signal_action": action,
                                "risk": risk,
                            },
                        }
                    )

        active_positions = (
            self.spot_position_store.active_positions()
            + self.futures_position_store.active_positions()
        )
        for position in active_positions:
            events.append(
                {
                    "event": "ORDER_OPEN",
                    "agent_id": "positions",
                    "generated_at": self._now(),
                    "payload": position,
                }
            )

        for strategy_id, path in self.auto_state_paths.items():
            auto_state = AutoTradeStateStore(path).load()
            if auto_state.get("halted"):
                events.append(
                    {
                        "event": "CIRCUIT_BREAKER",
                        "agent_id": "risk-manager",
                        "generated_at": self._now(),
                        "payload": {
                            "strategy_id": strategy_id,
                            "reason": auto_state.get("halt_reason"),
                            "halted_at": auto_state.get("halted_at"),
                        },
                    }
                )
        return events

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        offset = self.journal.size()
        for event in self._initial_events():
            yield event

        last_heartbeat = time.monotonic()
        while True:
            offset, records = self.journal.read_from(offset)
            if records:
                for record in records:
                    if record.get("event") == "STATE_CHANGED":
                        continue
                    yield record
                yield self._snapshot_event()
                last_heartbeat = time.monotonic()
            elif time.monotonic() - last_heartbeat >= 15:
                yield {
                    "event": "HEARTBEAT",
                    "agent_id": "system",
                    "generated_at": self._now(),
                    "payload": {"read_only": True},
                }
                last_heartbeat = time.monotonic()
            await asyncio.sleep(self.interval_seconds)
