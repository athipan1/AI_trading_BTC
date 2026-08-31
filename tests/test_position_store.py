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
