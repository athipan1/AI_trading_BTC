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
        if signal.action not in {TradeAction.BUY, TradeAction.SHORT}:
            return RiskDecision(approved=False, reason="signal is not an entry action")
        if equity <= 0:
            return RiskDecision(approved=False, reason="equity must be positive")
        if signal.entry_price is None or signal.stop_loss is None:
            return RiskDecision(approved=False, reason="entry and stop-loss are required")

        if signal.action == TradeAction.BUY:
            if signal.stop_loss >= signal.entry_price:
                return RiskDecision(approved=False, reason="long stop-loss must be below entry")
            risk_per_unit = signal.entry_price - signal.stop_loss
            if signal.take_profit is not None:
                if signal.take_profit <= signal.entry_price:
                    return RiskDecision(approved=False, reason="long take-profit must be above entry")
                reward_per_unit = signal.take_profit - signal.entry_price
                reward_risk = reward_per_unit / risk_per_unit
                if reward_risk < self.min_reward_risk:
                    return RiskDecision(
                        approved=False,
                        reason=f"reward/risk {reward_risk:.2f} below minimum {self.min_reward_risk:.2f}",
                    )
        else:
            if signal.stop_loss <= signal.entry_price:
                return RiskDecision(approved=False, reason="short stop-loss must be above entry")
            risk_per_unit = signal.stop_loss - signal.entry_price
            if signal.take_profit is not None:
                if signal.take_profit >= signal.entry_price:
                    return RiskDecision(approved=False, reason="short take-profit must be below entry")
                reward_per_unit = signal.entry_price - signal.take_profit
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
