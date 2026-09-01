from __future__ import annotations

from typing import Any

from app.auto_trading.state_store import AutoTradeStateStore, AutoTradingHalted
from app.execution.binance_futures_testnet import BinanceFuturesTestnetBroker
from app.models import TradeAction, TradeSignal
from app.monitoring.position_store import PositionStore
from app.notifications.line_messaging import (
    LineMessagingNotifier,
    format_auto_exit_message,
    format_open_order_message,
)
from app.risk.engine import RiskEngine
from app.strategies.triple_ema_short import TripleEMAShortStrategy


class FuturesShortAutoTrader:
    def __init__(
        self,
        *,
        broker: BinanceFuturesTestnetBroker,
        strategy: TripleEMAShortStrategy,
        risk_engine: RiskEngine,
        position_store: PositionStore,
        state_store: AutoTradeStateStore,
        notifier: LineMessagingNotifier | None,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        entry_notional_usdt: float = 55.0,
        candle_limit: int = 240,
    ) -> None:
        if entry_notional_usdt <= 0:
            raise ValueError("entry_notional_usdt must be positive")
        if candle_limit < strategy.min_candles:
            raise ValueError(f"candle_limit must be >= {strategy.min_candles}")
        self.broker = broker
        self.strategy = strategy
        self.risk_engine = risk_engine
        self.position_store = position_store
        self.state_store = state_store
        self.notifier = notifier
        self.symbol = symbol
        self.timeframe = timeframe
        self.entry_notional_usdt = float(entry_notional_usdt)
        self.candle_limit = candle_limit
        self.strategy_id = strategy.strategy_id

    def _active_position(self) -> dict[str, Any] | None:
        positions = self.position_store.active_positions(
            symbol=self.symbol,
            strategy_id=self.strategy_id,
        )
        if len(positions) > 1:
            raise AutoTradingHalted(
                f"strategy {self.strategy_id} has more than one tracked OPEN position"
            )
        return positions[0] if positions else None

    def _send_open_notification(
        self,
        *,
        order: dict[str, Any],
        position: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> str:
        if self.notifier is None:
            return "disabled"
        try:
            self.notifier.send_text(
                format_open_order_message(
                    symbol=self.symbol,
                    order_id=str(order["order_id"]),
                    side="short",
                    account_balance_usdt=float(snapshot["available_balance_usdt"]),
                    estimated_portfolio_value_usdt=float(snapshot["margin_balance_usdt"]),
                    entry_price=float(position["entry_price"]),
                    lot=float(position["quantity"]),
                    take_profit=float(position["take_profit"]),
                    stop_loss=float(position["stop_loss"]),
                    binance_open_orders=0,
                    tracked_positions=self.position_store.count_active(),
                    strategy_id=self.strategy_id,
                )
            )
        except Exception as exc:
            return f"warning:{exc.__class__.__name__}"
        return "sent"

    def _send_close_notification(
        self,
        *,
        reason: str,
        entry_position: dict[str, Any],
        exit_order: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> str:
        if self.notifier is None:
            return "disabled"
        try:
            self.notifier.send_text(
                format_auto_exit_message(
                    reason=reason,
                    symbol=self.symbol,
                    entry_order_id=str(entry_position["order_id"]),
                    exit_order_id=str(exit_order["order_id"]),
                    account_balance_usdt=float(snapshot["available_balance_usdt"]),
                    estimated_portfolio_value_usdt=float(snapshot["margin_balance_usdt"]),
                    entry_price=float(entry_position["entry_price"]),
                    exit_price=float(exit_order["average"]),
                    lot=float(exit_order["filled"]),
                    take_profit=float(entry_position["take_profit"]),
                    stop_loss=float(entry_position["stop_loss"]),
                    tracked_positions=self.position_store.count_active(),
                    strategy_id=self.strategy_id,
                )
            )
        except Exception as exc:
            return f"warning:{exc.__class__.__name__}"
        return "sent"

    @staticmethod
    def _levels_from_fill(signal: TradeSignal, fill_price: float) -> tuple[float, float]:
        if signal.entry_price is None or signal.stop_loss is None or signal.take_profit is None:
            raise AutoTradingHalted("SHORT signal is missing entry, SL, or TP")
        stop_pct = (signal.stop_loss - signal.entry_price) / signal.entry_price
        target_pct = (signal.entry_price - signal.take_profit) / signal.entry_price
        if not 0 < stop_pct < 1 or not 0 < target_pct < 1:
            raise AutoTradingHalted("SHORT signal contains invalid SL/TP distance")
        stop_loss = fill_price * (1 + stop_pct)
        take_profit = fill_price * (1 - target_pct)
        return take_profit, stop_loss

    def _enter_short(
        self,
        *,
        signal: TradeSignal,
        candle_ms: int,
        notional_usdt: float,
    ) -> dict[str, Any]:
        self.state_store.begin_order_attempt(
            action="SHORT",
            symbol=self.symbol,
            reason="TRIPLE_EMA_SHORT_ENTRY",
            candle_ms=candle_ms,
        )
        try:
            order = self.broker.place_market_short(self.symbol, notional_usdt)
        except Exception as exc:
            self.state_store.mark_order_uncertain(exc)
            raise AutoTradingHalted(
                "SHORT submission failed after local attempt began; automation halted"
            ) from exc
        order_id = order.get("order_id")
        fill_price = order.get("average")
        quantity = order.get("filled")
        if order_id is None or not fill_price or not quantity:
            error = RuntimeError("Futures SHORT acknowledgement is missing fill data")
            self.state_store.mark_order_uncertain(error)
            raise AutoTradingHalted(str(error))
        self.state_store.mark_order_acknowledged(str(order_id))
        take_profit, stop_loss = self._levels_from_fill(signal, float(fill_price))
        position = self.position_store.add_short_position(
            order_id=str(order_id),
            symbol=self.symbol,
            entry_price=float(fill_price),
            quantity=float(quantity),
            take_profit=take_profit,
            stop_loss=stop_loss,
            strategy_id=self.strategy_id,
            exit_mode=self.strategy.exit_mode,
        )
        snapshot = self.broker.account_snapshot(self.symbol)
        line_status = self._send_open_notification(
            order=order,
            position=position,
            snapshot=snapshot,
        )
        self.state_store.finalize_order_attempt()
        self.state_store.mark_candle_processed(candle_ms)
        return {
            "event": "SHORT_FILLED",
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candle_ms": candle_ms,
            "signal": signal.model_dump(mode="json"),
            "order": order,
            "position": position,
            "account": snapshot,
            "line_notification": line_status,
        }

    def _close_short(
        self,
        *,
        position: dict[str, Any],
        reason: str,
        candle_ms: int,
    ) -> dict[str, Any]:
        self.state_store.begin_order_attempt(
            action="BUY_TO_CLOSE",
            symbol=self.symbol,
            reason=reason,
            candle_ms=candle_ms,
        )
        try:
            order = self.broker.close_market_short(
                self.symbol,
                float(position["quantity"]),
            )
        except Exception as exc:
            self.state_store.mark_order_uncertain(exc)
            raise AutoTradingHalted(
                "SHORT close submission failed after local attempt began; automation halted"
            ) from exc
        order_id = order.get("order_id")
        exit_price = order.get("average")
        if order_id is None or not exit_price:
            error = RuntimeError("Futures close-SHORT acknowledgement is missing fill data")
            self.state_store.mark_order_uncertain(error)
            raise AutoTradingHalted(str(error))
        self.state_store.mark_order_acknowledged(str(order_id))
        closed = self.position_store.mark_closed(
            str(position["order_id"]),
            exit_order_id=str(order_id),
            exit_reason=reason,
            exit_price=float(exit_price),
        )
        snapshot = self.broker.account_snapshot(self.symbol)
        line_status = self._send_close_notification(
            reason=reason,
            entry_position=position,
            exit_order=order,
            snapshot=snapshot,
        )
        self.state_store.finalize_order_attempt()
        self.state_store.mark_candle_processed(candle_ms)
        return {
            "event": "SHORT_CLOSED",
            "strategy_id": self.strategy_id,
            "reason": reason,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candle_ms": candle_ms,
            "exit_order": order,
            "closed_position": closed,
            "account": snapshot,
            "line_notification": line_status,
        }

    def run_once(self) -> dict[str, Any]:
        self.state_store.assert_ready()
        candles = self.broker.fetch_closed_candles(
            self.symbol,
            interval=self.timeframe,
            limit=self.candle_limit,
        )
        candle_ms = candles[-1].timestamp_ms
        position = self._active_position()

        if position is not None:
            live_price = self.broker.current_price(self.symbol)
            if live_price >= float(position["stop_loss"]):
                return self._close_short(
                    position=position,
                    reason="SL_HIT",
                    candle_ms=candle_ms,
                )
            if live_price <= float(position["take_profit"]):
                return self._close_short(
                    position=position,
                    reason="TP_HIT",
                    candle_ms=candle_ms,
                )

        if self.state_store.last_processed_candle_ms() == candle_ms:
            return {
                "event": "WAIT_NEXT_CANDLE",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
            }

        signal, diagnostic = self.strategy.analyze_with_diagnostic(
            candles,
            self.symbol,
            self.timeframe,
        )
        if position is not None and signal.stop_loss is not None:
            position = self.position_store.update_stop_loss(
                str(position["order_id"]),
                float(signal.stop_loss),
            )

        if position is not None:
            if signal.action == TradeAction.EXIT:
                result = self._close_short(
                    position=position,
                    reason="EMA50_SHORT_CLOSE_EXIT",
                    candle_ms=candle_ms,
                )
                result["signal"] = signal.model_dump(mode="json")
                result["diagnostic"] = diagnostic.to_dict()
                return result
            self.state_store.mark_candle_processed(candle_ms)
            return {
                "event": "SHORT_HELD",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
                "signal": signal.model_dump(mode="json"),
                "diagnostic": diagnostic.to_dict(),
                "position": position,
            }

        if signal.action != TradeAction.SHORT:
            self.state_store.mark_candle_processed(candle_ms)
            return {
                "event": "NO_TRADE",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
                "signal": signal.model_dump(mode="json"),
                "diagnostic": diagnostic.to_dict(),
            }

        snapshot = self.broker.account_snapshot(self.symbol)
        equity = float(snapshot["margin_balance_usdt"])
        decision = self.risk_engine.evaluate_entry(signal, equity)
        if not decision.approved:
            self.state_store.mark_candle_processed(candle_ms)
            return {
                "event": "RISK_BLOCKED",
                "strategy_id": self.strategy_id,
                "signal": signal.model_dump(mode="json"),
                "risk": decision.model_dump(mode="json"),
                "diagnostic": diagnostic.to_dict(),
            }

        notional = min(float(decision.notional), self.entry_notional_usdt)
        minimum_notional = self.broker.minimum_entry_notional(self.symbol)
        safe_minimum_notional = minimum_notional * 1.01
        if notional < safe_minimum_notional:
            self.state_store.mark_candle_processed(candle_ms)
            return {
                "event": "ENTRY_SKIPPED_MIN_NOTIONAL",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
                "candidate_notional_usdt": notional,
                "minimum_notional_usdt": minimum_notional,
                "safe_minimum_notional_usdt": safe_minimum_notional,
                "signal": signal.model_dump(mode="json"),
                "risk": decision.model_dump(mode="json"),
                "diagnostic": diagnostic.to_dict(),
            }

        return self._enter_short(
            signal=signal,
            candle_ms=candle_ms,
            notional_usdt=notional,
        )
