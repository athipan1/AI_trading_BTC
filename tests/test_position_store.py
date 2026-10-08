from __future__ import annotations

from app.monitoring.position_store import PositionStore


def test_position_store_is_idempotent_and_tracks_trigger(tmp_path) -> None:
    store = PositionStore(tmp_path / "positions.json")
    first = store.add_long_position(
        order_id="123",
        symbol="BTC/USDT",
        entry_price=50_000,
        quantity=0.0002,
        take_profit=51_000,
        stop_loss=49_500,
    )
    duplicate = store.add_long_position(
        order_id="123",
        symbol="BTC/USDT",
        entry_price=50_000,
        quantity=0.0002,
        take_profit=51_000,
        stop_loss=49_500,
    )

    assert first["order_id"] == duplicate["order_id"]
    assert len(store.load()) == 1
    assert store.count_active() == 1

    triggered = store.mark_triggered("123", "TP_HIT", 51_010)
    assert triggered["status"] == "TP_HIT"
    assert triggered["notification_sent"] is False
    assert store.count_active() == 0
    assert len(store.pending_notifications()) == 1

    store.mark_notification_sent("123")
    assert store.pending_notifications() == []



def test_exchange_history_lost_quarantines_without_synthetic_exit_or_pnl(tmp_path) -> None:
    store = PositionStore(tmp_path / "positions.json")
    position = store.add_long_position(
        order_id="9324710",
        symbol="BTC/USDT",
        entry_price=86_629.86,
        quantity=0.00011,
        take_profit=87_439.84,
        stop_loss=86_224.86,
        strategy_id="baseline",
        exit_mode="fixed_tp_sl",
    )
    store.mark_triggered(position["order_id"], "SL_HIT", 86_218.0)

    orphaned = store.mark_exchange_history_lost(
        "9324710",
        reason="testnet history reset",
        evidence={"entry_order_lookup": "NOT_FOUND"},
    )

    assert orphaned["status"] == "ORPHANED"
    assert orphaned["reconciliation_status"] == "EXCHANGE_HISTORY_LOST"
    assert orphaned["orphaned_reason"] == "testnet history reset"
    assert orphaned["orphaned_evidence"]["entry_order_lookup"] == "NOT_FOUND"
    assert orphaned["exit_order_id"] is None
    assert orphaned["exit_price"] is None
    assert orphaned["gross_realized_pnl"] is None
    assert orphaned["net_realized_pnl"] is None
    assert orphaned["closed_at"] is None
    assert store.count_active(strategy_id="baseline") == 0
    assert store.unresolved_positions(strategy_id="baseline") == []


def test_exchange_history_lost_refuses_position_with_recorded_exit(tmp_path) -> None:
    store = PositionStore(tmp_path / "positions.json")
    store.add_long_position(
        order_id="123",
        symbol="BTC/USDT",
        entry_price=50_000,
        quantity=0.0002,
        take_profit=51_000,
        stop_loss=49_500,
    )
    store.mark_closed(
        "123",
        exit_order_id="456",
        exit_reason="SL_HIT",
        exit_price=49_500,
    )

    import pytest

    with pytest.raises(ValueError, match="CLOSED"):
        store.mark_exchange_history_lost(
            "123",
            reason="invalid orphan attempt",
            evidence={"proof": True},
        )
