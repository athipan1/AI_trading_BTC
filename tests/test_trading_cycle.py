from app.execution.paper import PaperBroker
from app.models import MarketRegime, TradeAction, TradeSignal
from app.risk.engine import RiskEngine
from app.trading_cycle import TradingCycle


class FakeMarketData:
    def __init__(self, candles):
        self.candles = candles

    def fetch_candles(self, symbol, timeframe, limit):
        return self.candles[-limit:]


class BuyStrategy:
    def analyze(self, candles, symbol, timeframe):
        price = candles[-1].close
        return TradeSignal(
            symbol=symbol,
            timeframe=timeframe,
            action=TradeAction.BUY,
            confidence=0.8,
            regime=MarketRegime.BULL_TREND,
            entry_price=price,
            stop_loss=price * 0.98,
            take_profit=price * 1.04,
            risk_reward=2.0,
        )


def test_cycle_places_only_paper_buy(trend_candles) -> None:
    broker = PaperBroker(10_000, fee_rate=0, slippage_bps=0)
    cycle = TradingCycle(FakeMarketData(trend_candles), BuyStrategy(), RiskEngine(), broker)
    result = cycle.run("BTC/USDT", "1h", 100)
    assert result.risk is not None and result.risk.approved
    assert result.fill is not None and result.fill.accepted
    assert result.portfolio.position_qty > 0


def test_cycle_does_not_duplicate_position(trend_candles) -> None:
    broker = PaperBroker(10_000, fee_rate=0, slippage_bps=0)
    cycle = TradingCycle(FakeMarketData(trend_candles), BuyStrategy(), RiskEngine(), broker)
    cycle.run("BTC/USDT", "1h", 100)
    second = cycle.run("BTC/USDT", "1h", 100)
    assert second.fill is None
    assert second.risk is not None and not second.risk.approved
