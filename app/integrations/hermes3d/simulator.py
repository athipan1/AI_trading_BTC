from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.integrations.hermes3d.journal import Hermes3DEventJournal


@dataclass(frozen=True)
class SimulationEventTemplate:
    agent_id: str
    payload: dict[str, Any]


class Hermes3DValidationEventSimulator:
    """Publish synthetic observability events without touching trading execution.

    This helper writes only to the Hermes3D append-only journal. It has no broker,
    exchange, risk, strategy, or position-store dependency and therefore cannot
    place/cancel orders or mutate a tracked position.
    """

    EVENT_TEMPLATES: dict[str, SimulationEventTemplate] = {
        "BUY_READY": SimulationEventTemplate(
            agent_id="baseline",
            payload={
                "strategy_id": "baseline",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "signal": {"action": "BUY", "regime": "VALIDATION"},
                "validation": True,
            },
        ),
        "SHORT_READY": SimulationEventTemplate(
            agent_id="triple_ema_short",
            payload={
                "strategy_id": "triple_ema_short",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "signal": {"action": "SHORT", "regime": "VALIDATION"},
                "validation": True,
            },
        ),
        "RISK_PASS": SimulationEventTemplate(
            agent_id="risk-manager",
            payload={
                "strategy_id": "baseline",
                "signal_action": "BUY",
                "risk": {"approved": True, "reason": "Hermes3D visual validation only"},
                "validation": True,
            },
        ),
        "ORDER_OPEN": SimulationEventTemplate(
            agent_id="positions",
            payload={
                "strategy_id": "triple_ema",
                "order_id": "validation-order",
                "symbol": "BTC/USDT",
                "side": "buy",
                "entry_price": 80000.0,
                "quantity": 0.0001,
                "take_profit": None,
                "stop_loss": 79000.0,
                "validation": True,
            },
        ),
        "TP_HIT": SimulationEventTemplate(
            agent_id="positions",
            payload={
                "strategy_id": "baseline",
                "order_id": "validation-order",
                "exit_order_id": "validation-exit",
                "symbol": "BTC/USDT",
                "entry_price": 80000.0,
                "exit_price": 82000.0,
                "validation": True,
            },
        ),
        "SL_HIT": SimulationEventTemplate(
            agent_id="positions",
            payload={
                "strategy_id": "baseline",
                "order_id": "validation-order",
                "exit_order_id": "validation-exit",
                "symbol": "BTC/USDT",
                "entry_price": 80000.0,
                "exit_price": 79000.0,
                "validation": True,
            },
        ),
        "CIRCUIT_BREAKER": SimulationEventTemplate(
            agent_id="risk-manager",
            payload={
                "strategy_id": "baseline",
                "reason": "Hermes3D visual validation only",
                "validation": True,
            },
        ),
    }

    def __init__(self, journal: Hermes3DEventJournal) -> None:
        self.journal = journal

    @classmethod
    def allowed_events(cls) -> tuple[str, ...]:
        return tuple(cls.EVENT_TEMPLATES)

    def publish(self, event_name: str) -> dict[str, Any]:
        normalized = event_name.strip().upper()
        template = self.EVENT_TEMPLATES.get(normalized)
        if template is None:
            raise ValueError(f"unsupported validation event: {event_name}")
        return self.journal.publish(
            event=normalized,
            agent_id=template.agent_id,
            payload=dict(template.payload),
        )
