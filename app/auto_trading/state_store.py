from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AutoTradingHalted(RuntimeError):
    """Raised when automatic execution cannot safely continue."""


class AutoTradeStateStore:
    ACTIVE_ATTEMPT_STATES = {"SUBMITTING", "ACKED", "UNCERTAIN"}

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _default() -> dict[str, Any]:
        return {
            "last_processed_candle_ms": None,
            "halted": False,
            "halt_reason": None,
            "order_attempt": None,
        }

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("auto trading state must contain a JSON object")
        state = self._default()
        state.update(payload)
        return state

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, self.path)

    def assert_ready(self) -> dict[str, Any]:
        state = self.load()
        if state.get("halted"):
            raise AutoTradingHalted(str(state.get("halt_reason") or "auto trading is halted"))
        attempt = state.get("order_attempt")
        if isinstance(attempt, dict) and attempt.get("status") in self.ACTIVE_ATTEMPT_STATES:
            reason = (
                "unfinished order attempt requires manual Binance Testnet reconciliation: "
                f"{attempt.get('action')} {attempt.get('symbol')} status={attempt.get('status')}"
            )
            state["halted"] = True
            state["halt_reason"] = reason
            self.save(state)
            raise AutoTradingHalted(reason)
        return state

    def last_processed_candle_ms(self) -> int | None:
        value = self.load().get("last_processed_candle_ms")
        return int(value) if isinstance(value, int) else None

    def mark_candle_processed(self, candle_ms: int) -> None:
        state = self.load()
        state["last_processed_candle_ms"] = int(candle_ms)
        self.save(state)

    def begin_order_attempt(
        self,
        *,
        action: str,
        symbol: str,
        reason: str,
        candle_ms: int | None,
    ) -> None:
        state = self.assert_ready()
        state["order_attempt"] = {
            "action": action.upper(),
            "symbol": symbol.upper(),
            "reason": reason,
            "candle_ms": candle_ms,
            "status": "SUBMITTING",
            "started_at": self._now(),
            "order_id": None,
            "error": None,
        }
        self.save(state)

    def mark_order_acknowledged(self, order_id: str) -> None:
        state = self.load()
        attempt = state.get("order_attempt")
        if not isinstance(attempt, dict):
            raise AutoTradingHalted("order acknowledgement has no matching local attempt")
        attempt["status"] = "ACKED"
        attempt["order_id"] = str(order_id)
        attempt["acknowledged_at"] = self._now()
        self.save(state)

    def mark_order_uncertain(self, error: Exception) -> None:
        state = self.load()
        attempt = state.get("order_attempt")
        if not isinstance(attempt, dict):
            attempt = {"status": "UNCERTAIN"}
            state["order_attempt"] = attempt
        attempt["status"] = "UNCERTAIN"
        attempt["error"] = f"{error.__class__.__name__}: {error}"
        attempt["failed_at"] = self._now()
        state["halted"] = True
        state["halt_reason"] = (
            "order result is uncertain; reconcile Binance Spot Testnet before restarting automation"
        )
        self.save(state)

    def finalize_order_attempt(self) -> None:
        state = self.load()
        attempt = state.get("order_attempt")
        if not isinstance(attempt, dict):
            raise AutoTradingHalted("cannot finalize missing order attempt")
        attempt["status"] = "FINALIZED"
        attempt["finalized_at"] = self._now()
        self.save(state)
