from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal, TypedDict

Hermes3DActivityState = Literal["IDLE", "WORKING", "SUCCESS", "WARNING", "ERROR"]

ACTIVITY_STATES: Final[frozenset[str]] = frozenset(
    {"IDLE", "WORKING", "SUCCESS", "WARNING", "ERROR"}
)

EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "AGENT_ACTIVITY",
        "BUY_READY",
        "SHORT_READY",
        "RISK_PASS",
        "ORDER_OPEN",
        "TP_HIT",
        "SL_HIT",
        "CIRCUIT_BREAKER",
        "STATE_CHANGED",
        "STATE_SNAPSHOT",
        "HEARTBEAT",
    }
)

TRADE_LIFECYCLE_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "BUY_READY",
        "SHORT_READY",
        "RISK_PASS",
        "ORDER_OPEN",
        "TP_HIT",
        "SL_HIT",
        "CIRCUIT_BREAKER",
    }
)

EVENT_CONTRACT_VERSION: Final[str] = "1.0"


class Hermes3DEventRecord(TypedDict):
    event: str
    agent_id: str
    generated_at: str
    payload: dict[str, Any]


_REQUIRED_PAYLOAD_FIELDS: Final[dict[str, frozenset[str]]] = {
    "AGENT_ACTIVITY": frozenset({"activity", "state", "message_key", "speech"}),
    "BUY_READY": frozenset({"strategy_id", "signal"}),
    "SHORT_READY": frozenset({"strategy_id", "signal"}),
    "RISK_PASS": frozenset({"strategy_id", "signal_action", "risk"}),
    "ORDER_OPEN": frozenset({"order_id"}),
    "TP_HIT": frozenset({"order_id"}),
    "SL_HIT": frozenset({"order_id"}),
    "CIRCUIT_BREAKER": frozenset({"strategy_id", "reason"}),
    "STATE_CHANGED": frozenset({"strategy_id", "source_event"}),
}


def _require_non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _validate_generated_at(value: Any) -> None:
    timestamp = _require_non_empty_string(value, field="generated_at")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("generated_at must include a timezone")


def _validate_agent_activity(payload: dict[str, Any]) -> None:
    state = _require_non_empty_string(payload.get("state"), field="payload.state").upper()
    if state not in ACTIVITY_STATES:
        raise ValueError(f"unsupported Hermes3D activity state: {state}")

    _require_non_empty_string(payload.get("activity"), field="payload.activity")
    _require_non_empty_string(payload.get("message_key"), field="payload.message_key")

    speech = payload.get("speech")
    if not isinstance(speech, dict):
        raise ValueError("payload.speech must be an object")
    _require_non_empty_string(speech.get("th"), field="payload.speech.th")
    _require_non_empty_string(speech.get("en"), field="payload.speech.en")


def validate_event_record(record: dict[str, Any], *, allow_extension_events: bool = False) -> None:
    """Validate the stable Hermes3D event envelope and known payload contracts.

    The function is intentionally read-only and does not normalize or mutate records.
    Extension events are rejected by default so producer/consumer drift is visible early.
    """

    event = _require_non_empty_string(record.get("event"), field="event").upper()
    if event not in EVENT_TYPES and not allow_extension_events:
        raise ValueError(f"unsupported Hermes3D event type: {event}")

    _require_non_empty_string(record.get("agent_id"), field="agent_id")
    _validate_generated_at(record.get("generated_at"))

    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    required = _REQUIRED_PAYLOAD_FIELDS.get(event, frozenset())
    missing = sorted(field for field in required if field not in payload)
    if missing:
        raise ValueError(f"{event} payload missing required fields: {', '.join(missing)}")

    if event == "AGENT_ACTIVITY":
        _validate_agent_activity(payload)


def event_contract_manifest() -> dict[str, Any]:
    """Return a JSON-serializable contract manifest for diagnostics and tests."""

    return {
        "version": EVENT_CONTRACT_VERSION,
        "event_types": sorted(EVENT_TYPES),
        "trade_lifecycle_events": sorted(TRADE_LIFECYCLE_EVENTS),
        "activity_states": sorted(ACTIVITY_STATES),
        "required_payload_fields": {
            event: sorted(fields) for event, fields in sorted(_REQUIRED_PAYLOAD_FIELDS.items())
        },
    }
