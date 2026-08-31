from __future__ import annotations

from decimal import Decimal

import pytest

from app.auto_trading.engine import TestnetAutoTrader
from app.auto_trading.state_store import AutoTradeStateStore, AutoTradingHalted
from app.models import Candle, MarketRegime, TradeAction, TradeSignal
from app.monitoring.position_store import PositionStore
from app.risk.engine import RiskEngine


class FakeStrategy:
    def __init__(self, action: TradeAction = TradeAction.BUY):
        self.action = action

    def analyze(self, candles, symbol, timeframe):
        if self.action == TradeAction.BUY:
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                action=TradeAction.BUY,
                confidence=0.8,
                regime=MarketRegime.BULL_TREND,
                entry_price=100.0,
                stop_loss=98.0,
                take_profit=104.0,
                risk_reward=2.0,
                reasons=["test buy"],
            )
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            action=self.action,
            confidence=0.7,
            regime=MarketRegime.SIDEWAYS,
            reasons=["test signal"],
        )


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send_text(self, text):
        self.messages.append(text)
        return {"sent": True, "status_code": 200}


class FakeBroker:
    max_order_notional_usdt = 25.0

    def __init__(self):
        self.price = 100.0
        self.buy_calls = 0
        self.sell_calls = 0
        self.fail_buy = False
        self.candle_ms = 60 * 3_600_000

    def fetch_closed_candles(self, symbol, interval, limit):
        return [
            Candle(
                timestamp_ms=(index + 1) * 3_600_000,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=10.0,
            )
            for index in range(60)
        ]

    def current_price(self, symbol):
        return self.price

    def account_snapshot(self, symbol):
        return {
            "symbol": symbol,
            "quote_free": 1000.0,
            "quote_total": 1000.0,
            "base_total": 1.0,
            "reference_price": self.price,
            "estimated_portfolio_value_quote": 1100.0,
            "open_orders_count": 0,
        }

    def _load_market(self, symbol):
        return {"filters": [{"filterType": "MIN_NOTIONAL", "minNotional": "5"}]}

    @staticmethod
    def _min_notional(market):
        return Decimal("5")

    def place_market_order(self, symbol, side, notional_usdt):
        self.buy_calls += 1
        if self.fail_buy:
            raise RuntimeError("simulated uncertain submit")
        return {
            "order_id": 1001,
            "average": 100.0,
            "filled": 0.1,
            "sellable_quantity": 0.1,
            "cost": 10.0,
            "side": "buy",
            "status": "FILLED",
        }

    def place_market_sell_quantity(self, symbol, quantity):
        self.sell_calls += 1
        return {
            "order_id": 2001,
            "average": self.price,
            "filled": quantity,
            "cost": quantity * self.price,
            "side": "sell",
            "status": "FILLED",
        }


def make_trader(tmp_path, broker=None, strategy=None, notifier=None):
    return TestnetAutoTrader(
        broker=broker or FakeBroker(),
        strategy=strategy or FakeStrategy(),
        risk_engine=RiskEngine(),
        position_store=PositionStore(tmp_path / "positions.json"),
        state_store=AutoTradeStateStore(tmp_path / "auto.json"),
        notifier=notifier,
        symbol="BTC/USDT",
        timeframe="1h",
        entry_notional_usdt=10,
        candle_limit=60,
    )


def test_buy_runs_once_per_closed_candle(tmp_path) -> None:
    broker = FakeBroker()
    notifier = FakeNotifier()
    trader = make_trader(tmp_path, broker=broker, notifier=notifier)

    first = trader.run_once()
    second = trader.run_once()

    assert first["event"] == "BUY_FILLED"
    assert second["event"] == "WAIT_NEXT_CANDLE"
    assert broker.buy_calls == 1
    assert trader.position_store.count_active() == 1
    assert len(notifier.messages) == 1
    assert "Trading BTC" in notifier.messages[0]


def test_tp_hit_sells_tracked_quantity_once(tmp_path) -> None:
    broker = FakeBroker()
    notifier = FakeNotifier()
    trader = make_trader(tmp_path, broker=broker, notifier=notifier)
    trader.run_once()

    broker.price = 105.0
    closed = trader.run_once()
    after = trader.run_once()

    assert closed["event"] == "POSITION_CLOSED"
    assert closed["reason"] == "TP_HIT"
    assert broker.sell_calls == 1
    assert trader.position_store.count_active() == 0
    assert after["event"] == "WAIT_NEXT_CANDLE"
    assert len(notifier.messages) == 2
    assert "ถึง TP" in notifier.messages[-1]


def test_uncertain_buy_halts_without_retry(tmp_path) -> None:
    broker = FakeBroker()
    broker.fail_buy = True
    trader = make_trader(tmp_path, broker=broker)

    with pytest.raises(AutoTradingHalted):
        trader.run_once()
    with pytest.raises(AutoTradingHalted):
        trader.run_once()

    assert broker.buy_calls == 1
    state = trader.state_store.load()
    assert state["halted"] is True
    assert state["order_attempt"]["status"] == "UNCERTAIN"


def test_no_position_exit_signal_does_not_submit_order(tmp_path) -> None:
    broker = FakeBroker()
    trader = make_trader(
        tmp_path,
        broker=broker,
        strategy=FakeStrategy(TradeAction.EXIT),
    )

    result = trader.run_once()

    assert result["event"] == "NO_TRADE"
    assert broker.buy_calls == 0
    assert broker.sell_calls == 0
