from __future__ import annotations

from app.monitoring.position_store import PositionStore
from scripts.monitor_binance_testnet_positions import check_once


class FakeBroker:
    def current_price(self, symbol: str) -> float:
        assert symbol == "BTC/USDT"
        return 51_010.0

    def account_snapshot(self, symbol: str) -> dict:
        assert symbol == "BTC/USDT"
        return {
            "quote_total": 990.0,
            "estimated_portfolio_value_quote": 1001.0,
            "open_orders_count": 0,
        }


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_text(self, text: str) -> dict:
        self.messages.append(text)
        return {"sent": True, "status_code": 200}


def test_tp_hit_sends_one_notification_and_stops_monitoring(tmp_path) -> None:
    store = PositionStore(tmp_path / "positions.json")
    store.add_long_position(
        order_id="123",
        symbol="BTC/USDT",
        entry_price=50_000,
        quantity=0.0002,
        take_profit=51_000,
        stop_loss=49_500,
    )
    notifier = FakeNotifier()
    broker = FakeBroker()

    events = check_once(broker, notifier, store)
    assert events[0]["event"] == "TP_HIT"
    assert len(notifier.messages) == 1
    assert "🎯 ถึง TP" in notifier.messages[0]
    assert store.count_active() == 0

    second_events = check_once(broker, notifier, store)
    assert second_events == []
    assert len(notifier.messages) == 1
