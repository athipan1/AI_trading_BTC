LIFECYCLE_STATES = frozenset(
    {
        "STRATEGY_EVALUATING",
        "SIGNAL_DETECTED",
        "RISK_CHECKING",
        "RISK_REJECTED",
        "RISK_APPROVED",
        "ORDER_OPENED",
        "POSITION_ACTIVE",
        "POSITION_CLOSED",
        "RECONCILING",
        "PNL_RECONCILED",
        "HALTED",
    }
)


def _string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def correlation_from_event(record: dict[str, object]) -> dict[str, str | None]:
    payload_value = record.get("payload")
    payload = payload_value if isinstance(payload_value, dict) else {}
    strategy_id = _string(payload.get("strategy_id"))
    if strategy_id is None and str(record.get("agent_id") or "") in {
        "baseline",
        "triple_ema",
        "triple_ema_short",
    }:
        strategy_id = _string(record.get("agent_id"))

    order_id = _string(payload.get("order_id"))
    symbol = _string(payload.get("symbol"))
    trade_id = _string(payload.get("trade_id"))
    if trade_id is None and strategy_id and order_id:
        trade_id = f"{strategy_id}:{order_id}"

    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "order_id": order_id,
        "trade_id": trade_id,
    }


def lifecycle_state_from_event(record: dict[str, object]) -> str | None:
    event = str(record.get("event") or "").upper()
    payload_value = record.get("payload")
    payload = payload_value if isinstance(payload_value, dict) else {}

    if event == "AGENT_ACTIVITY":
        activity = str(payload.get("activity") or "").lower()
        return {
            "strategy_check": "STRATEGY_EVALUATING",
            "risk_check": "RISK_CHECKING",
            "risk_blocked": "RISK_REJECTED",
            "risk_approved": "RISK_APPROVED",
            "order_filled_sync": "RECONCILING",
            "order_filled": "POSITION_ACTIVE",
            "position_closed_sync": "RECONCILING",
            "position_closed": "POSITION_CLOSED",
            "circuit_breaker": "HALTED",
        }.get(activity)

    return {
        "BUY_READY": "SIGNAL_DETECTED",
        "SHORT_READY": "SIGNAL_DETECTED",
        "RISK_PASS": "RISK_APPROVED",
        "ORDER_OPEN": "ORDER_OPENED",
        "TP_HIT": "POSITION_CLOSED",
        "SL_HIT": "POSITION_CLOSED",
        "CIRCUIT_BREAKER": "HALTED",
    }.get(event)


def lifecycle_snapshot(records: list[dict[str, object]]) -> dict[str, object]:
    """Project journal events into deterministic per-agent/per-trade lifecycle state.

    This function is read-only. It preserves the existing Hermes3D wire events and
    derives a canonical lifecycle for observability without changing execution.
    """

    by_agent: dict[str, dict[str, object]] = {}
    by_trade: dict[str, dict[str, object]] = {}

    for record in records:
        state = lifecycle_state_from_event(record)
        if state is None:
            continue
        if state not in LIFECYCLE_STATES:
            raise ValueError(f"unsupported lifecycle state: {state}")

        agent_id = _string(record.get("agent_id")) or "system"
        correlation = correlation_from_event(record)
        item: dict[str, object] = {
            "state": state,
            "event": _string(record.get("event")),
            "agent_id": agent_id,
            "generated_at": _string(record.get("generated_at")),
            "correlation": correlation,
        }
        by_agent[agent_id] = item
        trade_id = correlation.get("trade_id")
        if trade_id:
            by_trade[trade_id] = item

    return {
        "by_agent": by_agent,
        "by_trade": by_trade,
        "known_states": sorted(LIFECYCLE_STATES),
    }
