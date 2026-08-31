from __future__ import annotations

from app.notifications.line_messaging import (
    LineMessagingNotifier,
    format_level_hit_message,
    format_open_order_message,
)


class FakeResponse:
    status_code = 200
    ok = True

    def json(self):
        return {}


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers, json, timeout))
        return FakeResponse()


def test_pushes_text_with_bearer_token() -> None:
    session = FakeSession()
    notifier = LineMessagingNotifier("token-123", "U-target", session=session)

    result = notifier.send_text("Trading BTC\nhello")

    assert result == {"sent": True, "status_code": 200}
    url, headers, payload, timeout = session.calls[0]
    assert url == "https://api.line.me/v2/bot/message/push"
    assert headers["Authorization"] == "Bearer token-123"
    assert payload["to"] == "U-target"
    assert payload["messages"][0]["text"].startswith("Trading BTC")
    assert timeout == 10


def test_order_message_contains_requested_trading_fields() -> None:
    message = format_open_order_message(
        symbol="BTC/USDT",
        order_id="123",
        side="buy",
        account_balance_usdt=990,
        estimated_portfolio_value_usdt=1000,
        entry_price=50_000,
        lot=0.0002,
        take_profit=51_000,
        stop_loss=49_500,
        binance_open_orders=0,
        tracked_positions=1,
    )

    assert "Trading BTC" in message
    assert "ยอด USDT ในบัญชี: 990.00" in message
    assert "ราคาเข้า: 50,000.00" in message
    assert "Lot: 0.00020000 BTC" in message
    assert "TP: 51,000.00" in message
    assert "SL: 49,500.00" in message
    assert "Open orders ใน Binance: 0" in message
    assert "ออเดอร์ที่ระบบกำลังติดตาม: 1" in message


def test_level_message_labels_take_profit() -> None:
    message = format_level_hit_message(
        event="TP_HIT",
        symbol="BTC/USDT",
        order_id="123",
        account_balance_usdt=990,
        estimated_portfolio_value_usdt=1001,
        entry_price=50_000,
        hit_price=51_010,
        lot=0.0002,
        take_profit=51_000,
        stop_loss=49_500,
        binance_open_orders=0,
        tracked_positions=0,
    )
    assert "🎯 ถึง TP" in message
    assert "ราคาที่ตรวจพบ: 51,010.00 USDT" in message
