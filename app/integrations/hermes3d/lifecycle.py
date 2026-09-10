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

# Transaction progress is intentionally monotonic. RECONCILING is placed between
# order-open and position-active so fill reconciliation can advance an order, but a
# later duplicate ORDER_OPEN event cannot move an already-active position backwards.
TRADE_STATE_PROGRESS = {
    "STRATEGY_EVALUATING": 10,
    "SIGNAL_DETECTED": 20,
    "RISK_CHECKING": 30,
    "RISK_REJECTED": 40,
    "RISK_APPROVED": 40,
    "ORDER_OPENED": 50,
    "RECONCILING": 55,
    "POSITION_ACTIVE": 60,
    "POSITION_CLOSED": 70,
    "PNL_RECONCILED": 80,
    "HALTED": 90,
}


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


def _trade_history_key(item: dict[str, object]) -> str:
    return str(item.get("generated_at") or "")


def _project_trade(history: list[dict[str, object]]) -> dict[str, object]:
    ordered_history = sorted(history, key=_trade_history_key)
    current = ordered_history[0]
    for candidate in ordered_history[1:]:
        current_rank = TRADE_STATE_PROGRESS[str(current["state"])]
        candidate_rank = TRADE_STATE_PROGRESS[str(candidate["state"])]
        if candidate_rank >= current_rank:
            current = candidate

    trade_item = dict(current)
    trade_item["history"] = ordered_history
    trade_item["terminal"] = str(current["state"]) in TERMINAL_TRADE_STATES
    return trade_item


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
    trade gains a history and deterministic active-trade selection. Phase 4.5.1
    hardens transaction projection against duplicate or late lower-stage events so a
    trade's current state cannot regress even when sidecar event order is imperfect.
    """

    by_agent: dict[str, dict[str, object]] = {}
    trade_histories: dict[str, list[dict[str, object]]] = {}

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
            trade_histories.setdefault(trade_id, []).append(item)

    by_trade = {
        trade_id: _project_trade(history)
        for trade_id, history in trade_histories.items()
        if history
    }
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
