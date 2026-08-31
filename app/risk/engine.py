from __future__ import annotations

from app.models import RiskDecision, TradeAction, TradeSignal


class RiskEngine:
    def __init__(
        self,
        risk_per_trade_pct: float = 0.005,
        max_position_notional_pct: float = 0.25,
        min_reward_risk: float = 1.5,
    ) -> None:
        if not 0 < risk_per_trade_pct <= 0.01:
            raise ValueError("risk_per_trade_pct must be in (0, 0.01]")
        if not 0 < max_position_notional_pct <= 1:
            raise ValueError("max_position_notional_pct must be in (0, 1]")
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_notional_pct = max_position_notional_pct
        self.min_reward_risk = min_reward_risk

    def evaluate_entry(self, signal: TradeSignal, equity: float) -> RiskDecision:
        if signal.action != TradeAction.BUY:
            return RiskDecision(approved=False, reason="signal is not a BUY")
        if equity <= 0:
            return RiskDecision(approved=False, reason="equity must be positive")
        if signal.entry_price is None or signal.stop_loss is None or signal.take_profit is None:
            return RiskDecision(approved=False, reason="entry, stop-loss and take-profit are required")
        if signal.stop_loss >= signal.entry_price:
            return RiskDecision(approved=False, reason="long stop-loss must be below entry")
        if signal.take_profit <= signal.entry_price:
            return RiskDecision(approved=False, reason="long take-profit must be above entry")

        risk_per_unit = signal.entry_price - signal.stop_loss
        reward_per_unit = signal.take_profit - signal.entry_price
        reward_risk = reward_per_unit / risk_per_unit
        if reward_risk < self.min_reward_risk:
            return RiskDecision(
                approved=False,
                reason=f"reward/risk {reward_risk:.2f} below minimum {self.min_reward_risk:.2f}",
            )

        risk_budget = equity * self.risk_per_trade_pct
        quantity_by_risk = risk_budget / risk_per_unit
        max_notional = equity * self.max_position_notional_pct
        quantity_by_notional = max_notional / signal.entry_price
        quantity = min(quantity_by_risk, quantity_by_notional)
        if quantity <= 0:
            return RiskDecision(approved=False, reason="calculated quantity is zero")

        notional = quantity * signal.entry_price
        max_loss = quantity * risk_per_unit
        return RiskDecision(
            approved=True,
            quantity=quantity,
            max_loss=max_loss,
            notional=notional,
            reason="approved by Phase 1 risk limits",
        )
