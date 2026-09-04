from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.auto_trading.state_store import AutoTradeStateStore
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.monitoring.position_store import PositionStore


class Hermes3DJournalStateProjection:
    """CCXT-free read-only projection for Hermes3D observability.

    This projection never fetches exchange market data. It reconstructs the latest
    observable state from the append-only Hermes3D event journal plus the existing
    position and automation state stores.
    """

    STRATEGY_IDS = ("baseline", "triple_ema", "triple_ema_short")

    def __init__(
        self,
        *,
        journal: Hermes3DEventJournal,
        spot_position_store: PositionStore,
        futures_position_store: PositionStore,
        auto_state_paths: dict[str, str | Path],
        symbol: str,
        timeframe: str,
    ) -> None:
        self.journal = journal
        self.spot_position_store = spot_position_store
        self.futures_position_store = futures_position_store
        self.auto_state_paths = {
            strategy_id: Path(path) for strategy_id, path in auto_state_paths.items()
        }
        self.symbol = symbol
        self.timeframe = timeframe

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def registry() -> dict[str, Any]:
        return {
            "runtime": "ai-trading-btc",
            "mode": "read_only",
            "capabilities": [
                "market_state",
                "strategies",
                "risk",
                "positions",
                "realtime_events",
                "sse",
                "websocket",
            ],
            "event_types": [
                "BUY_READY",
                "SHORT_READY",
                "RISK_PASS",
                "ORDER_OPEN",
                "TP_HIT",
                "SL_HIT",
                "CIRCUIT_BREAKER",
            ],
            "event_endpoints": {
                "sse": "/events/stream",
                "websocket": "/events/ws",
            },
            "trade_execution": False,
            "models": {
                "readonly-observer": {
                    "name": "Read-only Observer",
                    "provider": "ai-trading-btc",
                }
            },
            "agents": [
                {"id": "market-data", "name": "Market Data", "role": "observer"},
                {"id": "baseline", "name": "Baseline Strategy", "role": "observer"},
                {"id": "triple_ema", "name": "Triple EMA Long", "role": "observer"},
                {
                    "id": "triple_ema_short",
                    "name": "Triple EMA Short",
                    "role": "observer",
                },
                {"id": "risk-manager", "name": "Risk Manager", "role": "observer"},
                {"id": "positions", "name": "Positions", "role": "observer"},
            ],
        }

    def _records(self) -> list[dict[str, Any]]:
        return self.journal.read_recent()

    @staticmethod
    def _latest_by_strategy(
        records: list[dict[str, Any]],
        event_names: set[str],
    ) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            if str(record.get("event")) not in event_names:
                continue
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            strategy_id = str(payload.get("strategy_id") or record.get("agent_id") or "")
            if strategy_id:
                latest[strategy_id] = record
        return latest

    def _automation_states(self) -> dict[str, dict[str, Any]]:
        return {
            strategy_id: AutoTradeStateStore(path).load()
            for strategy_id, path in self.auto_state_paths.items()
        }

    @staticmethod
    def _signal_from_record(record: dict[str, Any] | None) -> dict[str, Any]:
        if record is None:
            return {
                "action": "HOLD",
                "regime": "UNKNOWN",
                "reasons": ["No strategy event has been published yet"],
            }
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        signal = payload.get("signal")
        if isinstance(signal, dict):
            return signal
        return {
            "action": "HOLD",
            "regime": "UNKNOWN",
            "reasons": ["Latest strategy event does not contain a signal payload"],
        }

    @staticmethod
    def _risk_from_record(record: dict[str, Any] | None) -> dict[str, Any]:
        if record is None:
            return {"approved": False, "reason": "No risk event has been published yet"}
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        risk = payload.get("risk")
        if isinstance(risk, dict) and risk:
            return risk
        return {"approved": True, "reason": "RISK_PASS event observed"}

    @staticmethod
    def _diagnostic_from_record(record: dict[str, Any] | None) -> dict[str, Any]:
        if record is None:
            return {}
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        diagnostic = payload.get("diagnostic")
        return diagnostic if isinstance(diagnostic, dict) else {}

    @staticmethod
    def _first_value(diagnostic: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = diagnostic.get(key)
            if value is not None:
                return value
        return None

    def state(self) -> dict[str, Any]:
        records = self._records()
        ready_by_strategy = self._latest_by_strategy(records, {"BUY_READY", "SHORT_READY"})
        risk_by_strategy = self._latest_by_strategy(records, {"RISK_PASS"})
        automation_states = self._automation_states()

        strategy_states: list[dict[str, Any]] = []
        for strategy_id in self.STRATEGY_IDS:
            ready_record = ready_by_strategy.get(strategy_id)
            risk_record = risk_by_strategy.get(strategy_id)
            strategy_states.append(
                {
                    "strategy_id": strategy_id,
                    "signal": self._signal_from_record(ready_record),
                    "diagnostic": self._diagnostic_from_record(ready_record),
                    "risk": self._risk_from_record(risk_record),
                }
            )

        spot_positions = self.spot_position_store.active_positions(self.symbol)
        futures_positions = self.futures_position_store.active_positions(self.symbol)
        open_positions = len(spot_positions) + len(futures_positions)

        halted = {
            strategy_id: state
            for strategy_id, state in automation_states.items()
            if state.get("halted")
        }
        entry_signals = [
            item
            for item in strategy_states
            if str(item["signal"].get("action")) in {"BUY", "SHORT"}
        ]
        approved_entries = sum(bool(item["risk"].get("approved")) for item in entry_signals)

        latest_strategy_record = next(
            (record for record in reversed(records) if record.get("event") in {"BUY_READY", "SHORT_READY"}),
            None,
        )
        latest_payload = (
            latest_strategy_record.get("payload")
            if isinstance(latest_strategy_record, dict)
            and isinstance(latest_strategy_record.get("payload"), dict)
            else {}
        )
        latest_signal = latest_payload.get("signal") if isinstance(latest_payload.get("signal"), dict) else {}
        latest_diagnostic = (
            latest_payload.get("diagnostic")
            if isinstance(latest_payload.get("diagnostic"), dict)
            else {}
        )
        market_available = bool(latest_diagnostic)

        agent_statuses: dict[str, dict[str, Any]] = {
            "market-data": {
                "status": "STREAMING" if records else "WAITING_FOR_PRODUCER",
                "detail": (
                    "Market projection from trading-worker events"
                    if records
                    else "No Hermes3D journal events published yet"
                ),
            },
            "positions": {
                "status": "OPEN" if open_positions else "FLAT",
                "detail": f"{open_positions} tracked testnet positions",
            },
            "risk-manager": {
                "status": "CIRCUIT_BREAKER" if halted else ("PASS" if approved_entries else "WATCH"),
                "detail": (
                    f"halted strategies: {', '.join(sorted(halted))}"
                    if halted
                    else f"{approved_entries}/{len(entry_signals)} entry signals approved"
                ),
            },
        }
        for item in strategy_states:
            strategy_id = str(item["strategy_id"])
            action = str(item["signal"].get("action", "HOLD"))
            agent_statuses[strategy_id] = {
                "status": "ENTRY_READY" if action in {"BUY", "SHORT"} else action,
                "signal": action,
                "regime": item["signal"].get("regime", "UNKNOWN"),
                "risk_approved": bool(item["risk"].get("approved")),
                "detail": item["risk"].get("reason") or "Waiting for trading-worker event",
            }

        return {
            "generated_at": self._now(),
            "profileName": "btc-trading-room",
            "registry_profile": "btc-trading-room",
            "read_only": True,
            "degraded": not market_available,
            "source": "hermes3d_event_journal",
            "runtime": {
                "name": "AI Trading BTC",
                "version": "phase-1.6.1",
                "vendor": "athipan1",
                "status": "read_only",
                "active_model": "readonly-observer",
                "governance": "risk-engine-enforced",
            },
            "active": {agent_id: ["readonly-observer"] for agent_id in agent_statuses},
            "agent_statuses": agent_statuses,
            "permissions": {
                "market_read": True,
                "strategy_read": True,
                "risk_read": True,
                "positions_read": True,
                "events_read": True,
                "trade_execution": False,
                "order_cancel": False,
                "position_modify": False,
            },
            "market": {
                "symbol": latest_payload.get("symbol") or self.symbol,
                "timeframe": latest_payload.get("timeframe") or self.timeframe,
                "candle_timestamp_ms": latest_payload.get("candle_ms"),
                "price": self._first_value(latest_diagnostic, "price", "close"),
                "ema20": self._first_value(latest_diagnostic, "ema20", "ema_fast"),
                "ema50": self._first_value(latest_diagnostic, "ema50", "ema_slow"),
                "ema200": self._first_value(latest_diagnostic, "ema200"),
                "rsi14": self._first_value(latest_diagnostic, "rsi14", "rsi"),
                "momentum_pct": self._first_value(latest_diagnostic, "momentum_pct"),
                "atr14": self._first_value(latest_diagnostic, "atr14", "atr"),
                "regime": latest_signal.get("regime", "UNKNOWN"),
            },
            "strategies": strategy_states,
            "risk": {
                "entry_signals": len(entry_signals),
                "approved_entries": approved_entries,
                "execution_enabled": False,
                "circuit_breakers": {
                    strategy_id: {
                        "reason": state.get("halt_reason"),
                        "halted_at": state.get("halted_at"),
                    }
                    for strategy_id, state in halted.items()
                },
            },
            "positions": {
                "paper": None,
                "spot_testnet": spot_positions,
                "futures_testnet_short": futures_positions,
            },
        }
