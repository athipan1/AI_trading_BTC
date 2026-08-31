from app.models import MarketRegime, TradeAction, TradeSignal
from app.risk.engine import RiskEngine


def signal(rr: float = 2.0) -> TradeSignal:
    entry = 100.0
    stop = 95.0
    target = entry + (entry - stop) * rr
    return TradeSignal(
        symbol="BTC/USDT",
        timeframe="1h",
        action=TradeAction.BUY,
        confidence=0.8,
        regime=MarketRegime.BULL_TREND,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        risk_reward=rr,
    )


def test_risk_caps_loss_at_half_percent() -> None:
    decision = RiskEngine(risk_per_trade_pct=0.005, max_position_notional_pct=1).evaluate_entry(signal(), 10_000)
    assert decision.approved
    assert decision.max_loss <= 50.000001


def test_risk_rejects_poor_reward_risk() -> None:
    decision = RiskEngine(min_reward_risk=1.5).evaluate_entry(signal(1.0), 10_000)
    assert not decision.approved
