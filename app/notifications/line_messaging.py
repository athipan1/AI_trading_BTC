from __future__ import annotations

from typing import Any

import requests


class LineMessagingError(RuntimeError):
    """Raised when LINE Messaging API rejects a notification request."""


class LineMessagingNotifier:
    API_URL = "https://api.line.me/v2/bot/message/push"

    def __init__(
        self,
        channel_access_token: str,
        target_id: str,
        session: requests.Session | None = None,
    ) -> None:
        if not channel_access_token.strip():
            raise ValueError("LINE channel access token is required")
        if not target_id.strip():
            raise ValueError("LINE target ID is required")
        self.channel_access_token = channel_access_token.strip()
        self.target_id = target_id.strip()
        self.session = session or requests.Session()

    def send_text(self, text: str) -> dict[str, Any]:
        message = text.strip()
        if not message:
            raise ValueError("LINE message must not be empty")
        if len(message) > 5000:
            raise ValueError("LINE text message exceeds 5000 characters")

        try:
            response = self.session.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.channel_access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "to": self.target_id,
                    "messages": [{"type": "text", "text": message}],
                },
                timeout=10,
            )
        except requests.RequestException as exc:
            raise LineMessagingError(f"LINE network error: {exc.__class__.__name__}") from exc

        if not response.ok:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            detail = payload.get("message") if isinstance(payload, dict) else None
            raise LineMessagingError(
                f"LINE Messaging API error HTTP {response.status_code}: {detail or 'unknown error'}"
            )
        return {"sent": True, "status_code": response.status_code}


def _tp_text(take_profit: float | None) -> str:
    if take_profit is None:
        return "Dynamic / ไม่มี Fixed TP"
    return f"{take_profit:,.2f} USDT"


def _stop_label(strategy_id: str) -> str:
    if strategy_id.strip().lower() == "baseline":
        return "SL"
    return "SL/Exit Reference"


def format_open_order_message(
    *,
    symbol: str,
    order_id: str,
    side: str,
    account_balance_usdt: float,
    estimated_portfolio_value_usdt: float,
    entry_price: float,
    lot: float,
    take_profit: float | None,
    stop_loss: float,
    binance_open_orders: int,
    tracked_positions: int,
    strategy_id: str = "baseline",
) -> str:
    stop_label = _stop_label(strategy_id)
    return "\n".join(
        [
            "Trading BTC",
            f"🟢 เปิดออเดอร์ {side.upper()}",
            f"Strategy: {strategy_id.upper()}",
            f"คู่: {symbol}",
            f"Order ID: {order_id}",
            f"ยอด USDT ในบัญชี: {account_balance_usdt:,.2f}",
            f"มูลค่าพอร์ต BTC+USDT โดยประมาณ: {estimated_portfolio_value_usdt:,.2f} USDT",
            f"ราคาเข้า: {entry_price:,.2f} USDT",
            f"Lot: {lot:.8f} BTC",
            f"TP: {_tp_text(take_profit)}",
            f"{stop_label}: {stop_loss:,.2f} USDT",
            f"Open orders ใน Binance: {binance_open_orders}",
            f"ออเดอร์ที่ระบบกำลังติดตาม: {tracked_positions}",
        ]
    )


def format_level_hit_message(
    *,
    event: str,
    symbol: str,
    order_id: str,
    account_balance_usdt: float,
    estimated_portfolio_value_usdt: float,
    entry_price: float,
    hit_price: float,
    lot: float,
    take_profit: float | None,
    stop_loss: float,
    binance_open_orders: int,
    tracked_positions: int,
) -> str:
    normalized = event.upper()
    marker = "🎯" if normalized == "TP_HIT" else "🛑"
    label = "ถึง TP" if normalized == "TP_HIT" else "ถึง SL"
    return "\n".join(
        [
            "Trading BTC",
            f"{marker} {label}",
            f"คู่: {symbol}",
            f"Order ID: {order_id}",
            f"ยอด USDT ในบัญชี: {account_balance_usdt:,.2f}",
            f"มูลค่าพอร์ต BTC+USDT โดยประมาณ: {estimated_portfolio_value_usdt:,.2f} USDT",
            f"ราคาเข้า: {entry_price:,.2f} USDT",
            f"ราคาที่ตรวจพบ: {hit_price:,.2f} USDT",
            f"Lot: {lot:.8f} BTC",
            f"TP: {_tp_text(take_profit)}",
            f"SL: {stop_loss:,.2f} USDT",
            f"Open orders ใน Binance: {binance_open_orders}",
            f"ออเดอร์ที่ระบบกำลังติดตาม: {tracked_positions}",
        ]
    )


def format_auto_exit_message(
    *,
    reason: str,
    symbol: str,
    entry_order_id: str,
    exit_order_id: str,
    account_balance_usdt: float,
    estimated_portfolio_value_usdt: float,
    entry_price: float,
    exit_price: float,
    lot: float,
    take_profit: float | None,
    stop_loss: float,
    tracked_positions: int,
    strategy_id: str = "baseline",
) -> str:
    normalized = reason.upper()
    if normalized == "TP_HIT":
        marker = "🎯"
        label = "ถึง TP และปิดออเดอร์แล้ว"
    elif normalized == "SL_HIT":
        marker = "🛑"
        label = "ถึง SL และปิดออเดอร์แล้ว"
    elif normalized == "EMA50_CLOSE_EXIT":
        marker = "📉"
        label = "Close 1H ต่ำกว่า EMA50 และปิดออเดอร์แล้ว"
    elif normalized == "EMA50_SHORT_CLOSE_EXIT":
        marker = "📈"
        label = "Close 1H สูงกว่า EMA50 และปิด SHORT แล้ว"
    else:
        marker = "🔻"
        label = "Strategy EXIT และปิดออเดอร์แล้ว"
    stop_label = _stop_label(strategy_id)
    return "\n".join(
        [
            "Trading BTC",
            f"{marker} {label}",
            f"Strategy: {strategy_id.upper()}",
            f"คู่: {symbol}",
            f"Entry Order ID: {entry_order_id}",
            f"Exit Order ID: {exit_order_id}",
            f"ยอด USDT ในบัญชี: {account_balance_usdt:,.2f}",
            f"มูลค่าพอร์ต BTC+USDT โดยประมาณ: {estimated_portfolio_value_usdt:,.2f} USDT",
            f"ราคาเข้า: {entry_price:,.2f} USDT",
            f"ราคาปิด: {exit_price:,.2f} USDT",
            f"Lot: {lot:.8f} BTC",
            f"TP: {_tp_text(take_profit)}",
            f"{stop_label}: {stop_loss:,.2f} USDT",
            f"ออเดอร์ที่ระบบกำลังติดตาม: {tracked_positions}",
        ]
    )


def format_signal_diagnostic_message(
    *,
    symbol: str,
    timeframe: str,
    candle_ms: int,
    signal_action: str,
    regime: str,
    price: float,
    ema_fast: float,
    ema_slow: float,
    ema_bull_threshold: float,
    rsi: float,
    momentum_pct: float,
    atr: float,
    ema_trend_ok: bool,
    price_above_ema_fast_ok: bool,
    rsi_ok: bool,
    momentum_ok: bool,
    buy_ready: bool,
    blockers: list[str],
) -> str:
    def mark(value: bool) -> str:
        return "✅" if value else "❌"

    status = "BUY READY 🟢" if buy_ready else f"{signal_action.upper()} 🟡"
    lines = [
        "Trading BTC",
        "📊 Signal Diagnostic",
        f"คู่: {symbol} | TF: {timeframe}",
        f"Closed candle: {candle_ms}",
        f"Regime: {regime}",
        f"Signal: {status}",
        "",
        f"Price: {price:,.2f} USDT",
        f"EMA20: {ema_fast:,.2f}",
        f"EMA50: {ema_slow:,.2f}",
        f"RSI14: {rsi:.2f}",
        f"Momentum(10): {momentum_pct:+.4f}%",
        f"ATR14: {atr:,.2f}",
        "",
        f"{mark(ema_trend_ok)} EMA20 > EMA50 x 1.002 ({ema_bull_threshold:,.2f})",
        f"{mark(price_above_ema_fast_ok)} Price > EMA20",
        f"{mark(rsi_ok)} RSI >= 50",
        f"{mark(momentum_ok)} Momentum > 0%",
    ]
    if blockers:
        lines.extend(["", "เหตุผลที่ยังไม่ BUY:"])
        lines.extend(f"• {reason}" for reason in blockers)
    else:
        lines.extend(["", "ครบ 4 เงื่อนไข BUY แล้ว รอผ่าน Risk/Execution Gate"])
    return "\n".join(lines)
