from __future__ import annotations

from app.models import PaperFill, PortfolioSnapshot


class PaperBroker:
    def __init__(self, starting_balance: float, fee_rate: float = 0.001, slippage_bps: float = 5.0) -> None:
        if starting_balance <= 0:
            raise ValueError("starting_balance must be positive")
        self.cash = float(starting_balance)
        self.position_qty = 0.0
        self.avg_entry = 0.0
        self.realized_pnl = 0.0
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps

    def buy(self, quantity: float, price: float) -> PaperFill:
        if quantity <= 0 or price <= 0:
            return PaperFill(
                accepted=False,
                side="BUY",
                quantity=max(quantity, 0),
                requested_price=max(price, 1e-12),
                reason="quantity and price must be positive",
            )
        fill_price = price * (1 + self.slippage_bps / 10_000)
        gross = quantity * fill_price
        fee = gross * self.fee_rate
        total = gross + fee
        if total > self.cash:
            return PaperFill(
                accepted=False,
                side="BUY",
                quantity=quantity,
                requested_price=price,
                reason="insufficient paper cash",
            )

        old_cost = self.position_qty * self.avg_entry
        self.cash -= total
        self.position_qty += quantity
        self.avg_entry = (old_cost + gross) / self.position_qty
        return PaperFill(
            accepted=True,
            side="BUY",
            quantity=quantity,
            requested_price=price,
            fill_price=fill_price,
            fee=fee,
            reason="paper fill",
        )

    def sell(self, quantity: float, price: float) -> PaperFill:
        if quantity <= 0 or price <= 0:
            return PaperFill(
                accepted=False,
                side="SELL",
                quantity=max(quantity, 0),
                requested_price=max(price, 1e-12),
                reason="quantity and price must be positive",
            )
        if quantity > self.position_qty + 1e-12:
            return PaperFill(
                accepted=False,
                side="SELL",
                quantity=quantity,
                requested_price=price,
                reason="cannot sell more than paper position",
            )

        fill_price = price * (1 - self.slippage_bps / 10_000)
        gross = quantity * fill_price
        fee = gross * self.fee_rate
        self.cash += gross - fee
        self.realized_pnl += quantity * (fill_price - self.avg_entry) - fee
        self.position_qty -= quantity
        if self.position_qty <= 1e-12:
            self.position_qty = 0.0
            self.avg_entry = 0.0
        return PaperFill(
            accepted=True,
            side="SELL",
            quantity=quantity,
            requested_price=price,
            fill_price=fill_price,
            fee=fee,
            reason="paper fill",
        )

    def snapshot(self, mark_price: float) -> PortfolioSnapshot:
        market_value = self.position_qty * mark_price
        return PortfolioSnapshot(
            cash=max(self.cash, 0.0),
            position_qty=self.position_qty,
            avg_entry=self.avg_entry,
            realized_pnl=self.realized_pnl,
            equity=max(self.cash + market_value, 0.0),
        )
