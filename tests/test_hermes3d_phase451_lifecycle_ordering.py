from app.integrations.hermes3d.lifecycle import lifecycle_snapshot


def _record(
    event: str,
    *,
    agent_id: str,
    generated_at: str,
    activity: str | None = None,
) -> dict:
    payload = {
        "strategy_id": "triple_ema_short",
        "symbol": "BTC/USDT",
        "order_id": "28578553574",
    }
    if activity is not None:
        payload["activity"] = activity
    return {
        "event": event,
        "agent_id": agent_id,
        "generated_at": generated_at,
        "payload": payload,
    }


def test_runtime_sequence_does_not_regress_position_active_to_order_opened() -> None:
    records = [
        _record(
            "AGENT_ACTIVITY",
            agent_id="positions",
            generated_at="2026-09-09T23:23:54.836124+00:00",
            activity="order_filled_sync",
        ),
        _record(
            "AGENT_ACTIVITY",
            agent_id="positions",
            generated_at="2026-09-09T23:23:54.837328+00:00",
            activity="order_filled",
        ),
        _record(
            "ORDER_OPEN",
            agent_id="positions",
            generated_at="2026-09-09T23:23:54.839331+00:00",
        ),
    ]

    snapshot = lifecycle_snapshot(records)
    trade = snapshot["by_trade"]["triple_ema_short:28578553574"]

    assert [item["state"] for item in trade["history"]] == [
        "RECONCILING",
        "POSITION_ACTIVE",
        "ORDER_OPENED",
    ]
    assert trade["state"] == "POSITION_ACTIVE"
    assert trade["terminal"] is False
    assert snapshot["active_trade"]["state"] == "POSITION_ACTIVE"


def test_close_reconciliation_does_not_regress_active_position_before_close() -> None:
    records = [
        _record(
            "AGENT_ACTIVITY",
            agent_id="positions",
            generated_at="2026-09-10T10:00:00+00:00",
            activity="order_filled",
        ),
        _record(
            "AGENT_ACTIVITY",
            agent_id="positions",
            generated_at="2026-09-10T10:05:00+00:00",
            activity="position_closed_sync",
        ),
    ]

    trade = lifecycle_snapshot(records)["by_trade"]["triple_ema_short:28578553574"]

    assert trade["state"] == "POSITION_ACTIVE"
    assert trade["terminal"] is False


def test_terminal_close_advances_and_cannot_regress() -> None:
    records = [
        _record(
            "AGENT_ACTIVITY",
            agent_id="positions",
            generated_at="2026-09-10T10:00:00+00:00",
            activity="order_filled",
        ),
        _record(
            "TP_HIT",
            agent_id="positions",
            generated_at="2026-09-10T10:10:00+00:00",
        ),
        _record(
            "ORDER_OPEN",
            agent_id="positions",
            generated_at="2026-09-10T10:11:00+00:00",
        ),
    ]

    snapshot = lifecycle_snapshot(records)
    trade = snapshot["by_trade"]["triple_ema_short:28578553574"]

    assert trade["state"] == "POSITION_CLOSED"
    assert trade["terminal"] is True
    assert snapshot["active_trade"] is None
