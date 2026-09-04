from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, AsyncIterator

from app.auto_trading.state_store import AutoTradeStateStore
from app.integrations.hermes3d.adapter import Hermes3DReadOnlyAdapter
from app.monitoring.position_store import PositionStore


@dataclass(frozen=True)
class RuntimeEvent:
    event: str
    agent_id: str
    generated_at: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "agent_id": self.agent_id,
            "generated_at": self.generated_at,
            "payload": self.payload,
        }


class Hermes3DEventStream:
    """Read-only event detector for Hermes3D.

    The stream never submits or mutates orders. It observes the existing adapter,
    tracked position stores and auto-trading state files, then emits normalized
    events whenever their externally visible state changes.
    """

    def __init__(
        self,
        *,
        adapter: Hermes3DReadOnlyAdapter,
        spot_position_store: PositionStore,
        futures_position_store: PositionStore,
        auto_state_paths: dict[str, str | Path],
        interval_seconds: float = 1.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.adapter = adapter
        self.spot_position_store = spot_position_store
        self.futures_position_store = futures_position_store
        self.auto_state_paths = {
            strategy_id: Path(path) for strategy_id, path in auto_state_paths.items()
        }
        self.interval_seconds = float(interval_seconds)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _fingerprint(value: Any) -> str:
        if isinstance(value, dict):
            value = {key: item for key, item in value.items() if key != "generated_at"}
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(encoded.encode("utf-8")).hexdigest()

    def _closed_positions(self) -> dict[str, dict[str, Any]]:
        rows = self.spot_position_store.load() + self.futures_position_store.load()
        return {
            str(item.get("order_id")): item
            for item in rows
            if item.get("status") == "CLOSED" and item.get("order_id") is not None
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

    def _halted_states(self) -> dict[str, dict[str, Any]]:
        halted: dict[str, dict[str, Any]] = {}
        for strategy_id, path in self.auto_state_paths.items():
            state = AutoTradeStateStore(path).load()
            if state.get("halted"):
                halted[strategy_id] = state
        return halted

    def _strategy_events(self, state: dict[str, Any]) -> dict[str, RuntimeEvent]:
        result: dict[str, RuntimeEvent] = {}
        for item in state.get("strategies", []):
            strategy_id = str(item.get("strategy_id", "unknown"))
            signal = item.get("signal") or {}
            risk = item.get("risk") or {}
            action = str(signal.get("action", "HOLD"))
            if action in {"BUY", "SHORT"}:
                ready_name = "BUY_READY" if action == "BUY" else "SHORT_READY"
                result[f"{strategy_id}:ready"] = RuntimeEvent(
                    event=ready_name,
                    agent_id=strategy_id,
                    generated_at=self._now(),
                    payload={
                        "strategy_id": strategy_id,
                        "signal": signal,
                        "diagnostic": item.get("diagnostic") or {},
                    },
                )
                if bool(risk.get("approved")):
                    result[f"{strategy_id}:risk"] = RuntimeEvent(
                        event="RISK_PASS",
                        agent_id="risk-manager",
                        generated_at=self._now(),
                        payload={
                            "strategy_id": strategy_id,
                            "risk": risk,
                            "signal_action": action,
                        },
                    )
        return result

    def snapshot_events(self) -> dict[str, RuntimeEvent]:
        state = self.adapter.state()
        events = self._strategy_events(state)

        for order_id, position in self._active_positions().items():
            events[f"open:{order_id}"] = RuntimeEvent(
                event="ORDER_OPEN",
                agent_id="positions",
                generated_at=self._now(),
                payload=position,
            )

        for order_id, position in self._closed_positions().items():
            reason = str(position.get("exit_reason") or "POSITION_CLOSED").upper()
            if reason in {"TP_HIT", "SL_HIT"}:
                events[f"closed:{order_id}:{reason}"] = RuntimeEvent(
                    event=reason,
                    agent_id="positions",
                    generated_at=self._now(),
                    payload=position,
                )

        for strategy_id, state_row in self._halted_states().items():
            events[f"halted:{strategy_id}"] = RuntimeEvent(
                event="CIRCUIT_BREAKER",
                agent_id="risk-manager",
                generated_at=self._now(),
                payload={
                    "strategy_id": strategy_id,
                    "reason": state_row.get("halt_reason"),
                    "halted_at": state_row.get("halted_at"),
                },
            )

        events["snapshot"] = RuntimeEvent(
            event="STATE_SNAPSHOT",
            agent_id="market-data",
            generated_at=self._now(),
            payload=state,
        )
        return events

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        previous: dict[str, str] = {}
        first = True
        while True:
            current = self.snapshot_events()
            fingerprints = {
                key: self._fingerprint(event.payload) for key, event in current.items()
            }

            if first:
                snapshot = current.get("snapshot")
                if snapshot is not None:
                    yield snapshot.to_dict()
                for key, event in current.items():
                    if key == "snapshot" or key.startswith("closed:"):
                        continue
                    yield event.to_dict()
                previous = fingerprints
                first = False
                await asyncio.sleep(self.interval_seconds)
                continue

            for key, event in current.items():
                fingerprint = fingerprints[key]
                if previous.get(key) != fingerprint:
                    yield event.to_dict()

            previous = fingerprints
            await asyncio.sleep(self.interval_seconds)
