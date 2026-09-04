from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.integrations.hermes3d.events import Hermes3DEventStream
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.projection import Hermes3DJournalStateProjection
from app.integrations.hermes3d.sidecar import (
    Hermes3DLegacyLogSidecar,
    Hermes3DSidecarCursorStore,
    LogSource,
)
from app.monitoring.position_store import PositionStore


@dataclass(frozen=True)
class RealtimeValidationResult:
    passed: bool
    observed_events: tuple[str, ...]
    required_events: tuple[str, ...]
    journal_records: int
    read_only: bool
    trade_execution: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "observed_events": list(self.observed_events),
            "required_events": list(self.required_events),
            "journal_records": self.journal_records,
            "read_only": self.read_only,
            "trade_execution": self.trade_execution,
        }


def _append_json_line(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()


async def _collect_until(
    iterator: Any,
    *,
    required: set[str],
    timeout_seconds: float = 3.0,
) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    remaining = set(required)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while remaining:
        timeout = deadline - loop.time()
        if timeout <= 0:
            raise TimeoutError(f"timed out waiting for events: {sorted(remaining)}")
        event = await asyncio.wait_for(anext(iterator), timeout=timeout)
        observed.append(event)
        remaining.discard(str(event.get("event") or ""))
    return observed


async def validate_realtime_pipeline() -> RealtimeValidationResult:
    """Validate log -> sidecar -> journal -> realtime stream in an isolated sandbox.

    No production logs, state files, exchange clients, API credentials, or order
    execution paths are used. Synthetic JSON records are written only inside a
    temporary directory and are removed automatically when validation finishes.
    """

    required_events = {
        "BUY_READY",
        "SHORT_READY",
        "RISK_PASS",
        "ORDER_OPEN",
        "TP_HIT",
        "SL_HIT",
        "CIRCUIT_BREAKER",
    }

    with tempfile.TemporaryDirectory(prefix="hermes3d-e2e-") as temp_dir:
        root = Path(temp_dir)
        spot_log = root / "spot.log"
        futures_log = root / "futures.log"
        spot_log.touch()
        futures_log.touch()

        journal = Hermes3DEventJournal(root / "events.jsonl")
        sidecar = Hermes3DLegacyLogSidecar(
            sources=[
                LogSource("spot", spot_log),
                LogSource("futures-short", futures_log),
            ],
            journal=journal,
            cursor_store=Hermes3DSidecarCursorStore(root / "cursors.json"),
            start_at_end=True,
        )

        spot_positions = PositionStore(root / "spot-positions.json")
        futures_positions = PositionStore(root / "futures-positions.json")
        auto_state_paths = {
            "baseline": root / "baseline-auto.json",
            "triple_ema": root / "triple-auto.json",
            "triple_ema_short": root / "short-auto.json",
        }
        projection = Hermes3DJournalStateProjection(
            journal=journal,
            spot_position_store=spot_positions,
            futures_position_store=futures_positions,
            auto_state_paths=auto_state_paths,
            symbol="BTC/USDT",
            timeframe="1h",
        )
        stream = Hermes3DEventStream(
            state_reader=projection,
            journal=journal,
            spot_position_store=spot_positions,
            futures_position_store=futures_positions,
            auto_state_paths=auto_state_paths,
            interval_seconds=0.01,
        )
        iterator = stream.stream()

        initial = await asyncio.wait_for(anext(iterator), timeout=1.0)
        if initial.get("event") != "STATE_SNAPSHOT":
            raise AssertionError("realtime stream did not start with STATE_SNAPSHOT")

        _append_json_line(
            spot_log,
            {
                "event": "BUY_FILLED",
                "strategy_id": "baseline",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "candle_ms": 1,
                "signal": {"action": "BUY", "regime": "BULL_TREND"},
                "risk": {"approved": True, "reason": "isolated validation"},
                "diagnostic": {"price": 80000.0, "ema20": 79500.0, "ema50": 79000.0},
                "position": {
                    "order_id": "validation-long",
                    "symbol": "BTC/USDT",
                    "side": "buy",
                    "entry_price": 80000.0,
                    "quantity": 0.001,
                    "take_profit": 82000.0,
                    "stop_loss": 79000.0,
                },
            },
        )
        _append_json_line(
            futures_log,
            {
                "event": "SHORT_FILLED",
                "strategy_id": "triple_ema_short",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "candle_ms": 2,
                "signal": {"action": "SHORT", "regime": "BEAR_TREND"},
                "risk": {"approved": True, "reason": "isolated validation"},
                "position": {
                    "order_id": "validation-short",
                    "symbol": "BTC/USDT",
                    "side": "sell",
                    "entry_price": 80000.0,
                    "quantity": 0.001,
                    "take_profit": 78000.0,
                    "stop_loss": 81000.0,
                },
            },
        )
        first_poll = sidecar.poll_once()
        if first_poll["events"] <= 0:
            raise AssertionError("sidecar did not publish entry events")

        observed = await _collect_until(
            iterator,
            required={"BUY_READY", "SHORT_READY", "RISK_PASS", "ORDER_OPEN"},
        )

        _append_json_line(
            spot_log,
            {
                "event": "POSITION_CLOSED",
                "strategy_id": "baseline",
                "symbol": "BTC/USDT",
                "reason": "SL_HIT",
                "closed_position": {
                    "order_id": "validation-long",
                    "exit_order_id": "validation-long-exit",
                    "symbol": "BTC/USDT",
                    "entry_price": 80000.0,
                    "exit_price": 79000.0,
                },
            },
        )
        _append_json_line(
            futures_log,
            {
                "event": "SHORT_CLOSED",
                "strategy_id": "triple_ema_short",
                "symbol": "BTC/USDT",
                "reason": "TP_HIT",
                "closed_position": {
                    "order_id": "validation-short",
                    "exit_order_id": "validation-short-exit",
                    "symbol": "BTC/USDT",
                    "entry_price": 80000.0,
                    "exit_price": 78000.0,
                },
            },
        )
        _append_json_line(
            futures_log,
            {
                "event": "FUTURES_SHORT_HALTED",
                "strategy_id": "triple_ema_short",
                "reason": "isolated validation circuit breaker",
                "state": {"halted": True, "halt_reason": "isolated validation circuit breaker"},
            },
        )
        second_poll = sidecar.poll_once()
        if second_poll["events"] <= 0:
            raise AssertionError("sidecar did not publish exit/halt events")

        observed.extend(
            await _collect_until(
                iterator,
                required={"TP_HIT", "SL_HIT", "CIRCUIT_BREAKER"},
            )
        )

        state = projection.state()
        permissions = state.get("permissions") if isinstance(state.get("permissions"), dict) else {}
        observed_names = tuple(dict.fromkeys(str(item.get("event") or "") for item in observed))
        journal_records = len(journal.read_recent())
        passed = (
            required_events.issubset(set(observed_names))
            and bool(state.get("read_only"))
            and permissions.get("trade_execution") is False
        )
        await iterator.aclose()

        return RealtimeValidationResult(
            passed=passed,
            observed_events=observed_names,
            required_events=tuple(sorted(required_events)),
            journal_records=journal_records,
            read_only=bool(state.get("read_only")),
            trade_execution=bool(permissions.get("trade_execution")),
        )
