from __future__ import annotations

from app.execution.paper import PaperBroker
from app.models import CycleResult, RiskDecision, TradeAction
from app.risk.engine import RiskEngine
from app.strategies.baseline import BaselineStrategy


class TradingCycle:
    def __init__(self, market_data, strategy: BaselineStrategy, risk: RiskEngine, broker: PaperBroker) -> None:
        self.market_data = market_data
        self.strategy = strategy
        self.risk = risk
        self.broker = broker

    def run(self, symbol: str, timeframe: str, limit: int = 250) -> CycleResult:
        candles = self.market_data.fetch_candles(symbol, timeframe, limit)
        signal = self.strategy.analyze(candles, symbol, timeframe)
        price = candles[-1].close
        before = self.broker.snapshot(price)

        if signal.action == TradeAction.BUY:
            if before.position_qty > 0:
                return CycleResult(
                    symbol=symbol,
                    timeframe=timeframe,
                    signal=signal,
                    risk=RiskDecision(approved=False, reason="paper position already open"),
                    portfolio=before,
                )
            decision = self.risk.evaluate_entry(signal, before.equity)
            fill = self.broker.buy(decision.quantity, price) if decision.approved else None
            return CycleResult(
                symbol=symbol,
                timeframe=timeframe,
                signal=signal,
                risk=decision,
                fill=fill,
                portfolio=self.broker.snapshot(price),
            )

        if signal.action == TradeAction.EXIT and before.position_qty > 0:
            fill = self.broker.sell(before.position_qty, price)
            return CycleResult(
                symbol=symbol,
                timeframe=timeframe,
                signal=signal,
                fill=fill,
                portfolio=self.broker.snapshot(price),
            )

        return CycleResult(
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            portfolio=before,
        )
