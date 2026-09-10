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

ACTIVE_TRADE_STATES = frozenset({"ORDER_OPENED", "POSITION_ACTIVE", "RECONCILING"})
TERMINAL_TRADE_STATES = frozenset({"POSITION_CLOSED", "PNL_RECONCILED", "HALTED"})


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


def _trade_item(
    *,
    state: str,
    record: dict[str, object],
    agent_id: str,
    correlation: dict[str, str | None],
) -> dict[str, object]:
    return {
        "state": state,
        "event": _string(record.get("event")),
        "agent_id": agent_id,
        "generated_at": _string(record.get("generated_at")),
        "correlation": correlation,
    }


def _select_active_trade(by_trade: dict[str, dict[str, object]]) -> dict[str, object] | None:
    candidates = [
        item for item in by_trade.values() if str(item.get("state")) in ACTIVE_TRADE_STATES
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: str(item.get("generated_at") or ""))


def lifecycle_snapshot(records: list[dict[str, object]]) -> dict[str, object]:
    """Project journal events into per-agent and transaction-scoped lifecycle state.

    Phase 4.5 keeps the Phase 4.4 per-agent projection intact, while each correlated
    trade gains a history and deterministic active-trade selection. Events without a
    trade id can update an agent without contaminating another trade's lifecycle.
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
        item = _trade_item(
            state=state,
            record=record,
            agent_id=agent_id,
            correlation=correlation,
        )
        by_agent[agent_id] = item

        trade_id = correlation.get("trade_id")
        if trade_id:
            previous = by_trade.get(trade_id)
            history = list(previous.get("history", [])) if previous else []
            history.append(item)
            trade_item = dict(item)
            trade_item["history"] = history
            trade_item["terminal"] = state in TERMINAL_TRADE_STATES
            by_trade[trade_id] = trade_item

    active_trade = _select_active_trade(by_trade)
    return {
        "by_agent": by_agent,
        "by_trade": by_trade,
        "trade_lifecycles": by_trade,
        "active_trade": active_trade,
        "known_states": sorted(LIFECYCLE_STATES),
        "active_states": sorted(ACTIVE_TRADE_STATES),
        "terminal_states": sorted(TERMINAL_TRADE_STATES),
    }
