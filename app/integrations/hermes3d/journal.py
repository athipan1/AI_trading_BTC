from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Hermes3DEventJournal:
    """Append-only local event bus shared by trading workers and the read-only API."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def publish(
        self,
        *,
        event: str,
        agent_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "event": event,
            "agent_id": agent_id,
            "generated_at": self._now(),
            "payload": payload,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)
        return record

    def publish_result(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        published: list[dict[str, Any]] = []
        strategy_id = str(result.get("strategy_id") or "unknown")
        signal = result.get("signal") if isinstance(result.get("signal"), dict) else {}
        action = str(signal.get("action") or "")
        event_name = str(result.get("event") or "")

        if action in {"BUY", "SHORT"}:
            published.append(
                self.publish(
                    event="BUY_READY" if action == "BUY" else "SHORT_READY",
                    agent_id=strategy_id,
                    payload={
                        "strategy_id": strategy_id,
                        "symbol": result.get("symbol"),
                        "timeframe": result.get("timeframe"),
                        "candle_ms": result.get("candle_ms"),
                        "signal": signal,
                        "diagnostic": result.get("diagnostic"),
                    },
                )
            )

        risk = result.get("risk") if isinstance(result.get("risk"), dict) else {}
        risk_passed = bool(risk.get("approved")) or event_name in {"BUY_FILLED", "SHORT_FILLED"}
        if action in {"BUY", "SHORT"} and risk_passed:
            published.append(
                self.publish(
                    event="RISK_PASS",
                    agent_id="risk-manager",
                    payload={
                        "strategy_id": strategy_id,
                        "signal_action": action,
                        "risk": risk,
                    },
                )
            )

        if event_name in {"BUY_FILLED", "SHORT_FILLED"}:
            position = result.get("position") if isinstance(result.get("position"), dict) else {}
            published.append(
                self.publish(
                    event="ORDER_OPEN",
                    agent_id="positions",
                    payload={
                        "strategy_id": strategy_id,
                        "order_id": position.get("order_id"),
                        "symbol": position.get("symbol", result.get("symbol")),
                        "side": position.get("side"),
                        "entry_price": position.get("entry_price"),
                        "quantity": position.get("quantity"),
                        "take_profit": position.get("take_profit"),
                        "stop_loss": position.get("stop_loss"),
                    },
                )
            )

        reason = str(result.get("reason") or "").upper()
        if event_name in {"POSITION_CLOSED", "SHORT_CLOSED"} and reason in {"TP_HIT", "SL_HIT"}:
            closed = (
                result.get("closed_position")
                if isinstance(result.get("closed_position"), dict)
                else {}
            )
            published.append(
                self.publish(
                    event=reason,
                    agent_id="positions",
                    payload={
                        "strategy_id": strategy_id,
                        "order_id": closed.get("order_id"),
                        "exit_order_id": closed.get("exit_order_id"),
                        "symbol": closed.get("symbol", result.get("symbol")),
                        "exit_price": closed.get("exit_price"),
                        "entry_price": closed.get("entry_price"),
                    },
                )
            )

        published.append(
            self.publish(
                event="STATE_CHANGED",
                agent_id="market-data",
                payload={
                    "strategy_id": strategy_id,
                    "source_event": event_name,
                    "candle_ms": result.get("candle_ms"),
                },
            )
        )
        return published

    def publish_circuit_breaker(self, *, strategy_id: str, reason: str) -> dict[str, Any]:
        return self.publish(
            event="CIRCUIT_BREAKER",
            agent_id="risk-manager",
            payload={"strategy_id": strategy_id, "reason": reason},
        )

    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def read_from(self, offset: int) -> tuple[int, list[dict[str, Any]]]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        try:
            current_size = self.path.stat().st_size
        except FileNotFoundError:
            return 0, []
        if current_size < offset:
            offset = 0
        with self.path.open("rb") as handle:
            handle.seek(offset)
            rows = handle.readlines()
            next_offset = handle.tell()
        records: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return next_offset, records
