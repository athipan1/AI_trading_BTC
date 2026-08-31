from app.models import TradeAction
from app.strategies.baseline import BaselineStrategy


def test_baseline_can_generate_buy_in_uptrend(trend_candles) -> None:
    signal = BaselineStrategy().analyze(trend_candles, "BTC/USDT", "1h")
    assert signal.action == TradeAction.BUY
    assert signal.stop_loss is not None
    assert signal.take_profit is not None
    assert signal.risk_reward == 2.0
