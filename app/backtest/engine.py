from __future__ import annotations

from dataclasses import dataclass

from app.execution.paper import PaperBroker
from app.models import Candle, TradeAction
from app.risk.engine import RiskEngine


@dataclass(frozen=True)
class BacktestResult:
    starting_equity: float
    final_equity: float
    return_pct: float
    closed_trades: int
    wins: int
    losses: int
    win_rate: float
    max_drawdown_pct: float


class BacktestEngine:
    def __init__(
        self,
        strategy,
        risk: RiskEngine,
        starting_balance: float,
        fee_rate: float,
        slippage_bps: float,
    ) -> None:
        self.strategy = strategy
        self.risk = risk
        self.starting_balance = starting_balance
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps

    def run(self, candles: list[Candle], symbol: str, timeframe: str) -> BacktestResult:
        if len(candles) < 80:
            raise ValueError("backtest requires at least 80 candles")
        broker = PaperBroker(self.starting_balance, self.fee_rate, self.slippage_bps)
        peak_equity = self.starting_balance
        max_drawdown = 0.0
        closed = wins = losses = 0
        entry_equity: float | None = None
        active_stop: float | None = None
        active_target: float | None = None

        for i in range(60, len(candles)):
            current = candles[i]
            history = candles[:i]

            if broker.position_qty > 0 and active_stop is not None and current.low <= active_stop:
                broker.sell(broker.position_qty, active_stop)
                after = broker.snapshot(active_stop).equity
                closed += 1
                wins += int(entry_equity is not None and after > entry_equity)
                losses += int(entry_equity is not None and after <= entry_equity)
                entry_equity = None
                active_stop = active_target = None
            elif broker.position_qty > 0 and active_target is not None and current.high >= active_target:
                broker.sell(broker.position_qty, active_target)
                after = broker.snapshot(active_target).equity
                closed += 1
                wins += int(entry_equity is not None and after > entry_equity)
                losses += int(entry_equity is not None and after <= entry_equity)
                entry_equity = None
                active_stop = active_target = None
            else:
                signal = self.strategy.analyze(history, symbol, timeframe)
                execution_price = current.open
                if signal.action == TradeAction.BUY and broker.position_qty == 0:
                    decision = self.risk.evaluate_entry(signal, broker.snapshot(execution_price).equity)
                    if decision.approved:
                        # Rebase risk distances from signal-close onto next candle open.
                        stop_distance = signal.entry_price - signal.stop_loss  # type: ignore[operator]
                        target_distance = signal.take_profit - signal.entry_price  # type: ignore[operator]
                        active_stop = execution_price - stop_distance
                        active_target = execution_price + target_distance
                        fill = broker.buy(decision.quantity, execution_price)
                        if fill.accepted:
                            entry_equity = broker.snapshot(execution_price).equity
                        else:
                            active_stop = active_target = None
                elif signal.action == TradeAction.EXIT and broker.position_qty > 0:
                    broker.sell(broker.position_qty, execution_price)
                    after = broker.snapshot(execution_price).equity
                    closed += 1
                    wins += int(entry_equity is not None and after > entry_equity)
                    losses += int(entry_equity is not None and after <= entry_equity)
                    entry_equity = None
                    active_stop = active_target = None

            equity = broker.snapshot(current.close).equity
            peak_equity = max(peak_equity, equity)
            if peak_equity > 0:
                max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)

        final_equity = broker.snapshot(candles[-1].close).equity
        win_rate = wins / closed if closed else 0.0
        return BacktestResult(
            starting_equity=self.starting_balance,
            final_equity=final_equity,
            return_pct=((final_equity / self.starting_balance) - 1) * 100,
            closed_trades=closed,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            max_drawdown_pct=max_drawdown * 100,
        )
