from __future__ import annotations

from typing import Any

from app.auto_trading.state_store import AutoTradeStateStore, AutoTradingHalted
from app.execution.binance_testnet import BinanceTestnetBroker
from app.models import TradeAction, TradeSignal
from app.monitoring.position_store import PositionStore
from app.notifications.line_messaging import (
    LineMessagingNotifier,
    format_auto_exit_message,
    format_open_order_message,
    format_signal_diagnostic_message,
)
from app.risk.engine import RiskEngine


class TestnetAutoTrader:
    """Fail-closed long-only automatic trader for one strategy and one symbol."""

    def __init__(
        self,
        *,
        broker: BinanceTestnetBroker,
        strategy: Any,
        risk_engine: RiskEngine,
        position_store: PositionStore,
        state_store: AutoTradeStateStore,
        notifier: LineMessagingNotifier | None = None,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        entry_notional_usdt: float = 10.0,
        candle_limit: int = 120,
        strategy_id: str | None = None,
    ) -> None:
        if entry_notional_usdt <= 0:
            raise ValueError("entry_notional_usdt must be positive")
        if entry_notional_usdt > broker.max_order_notional_usdt:
            raise ValueError("entry_notional_usdt exceeds Binance Testnet hard order cap")
        self.broker = broker
        self.strategy = strategy
        self.risk_engine = risk_engine
        self.position_store = position_store
        self.state_store = state_store
        self.notifier = notifier
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.entry_notional_usdt = float(entry_notional_usdt)
        self.candle_limit = candle_limit
        self.strategy_id = (strategy_id or getattr(strategy, "strategy_id", "baseline")).lower()
        self.exit_mode = str(getattr(strategy, "exit_mode", "fixed_tp_sl"))

    def _active_position(self) -> dict[str, Any] | None:
        positions = self.position_store.active_positions(
            self.symbol,
            strategy_id=self.strategy_id,
        )
        if len(positions) > 1:
            reason = (
                f"more than one tracked OPEN position exists for {self.symbol} "
                f"strategy={self.strategy_id}"
            )
            self.state_store.halt(reason)
            raise AutoTradingHalted(reason)
        return positions[0] if positions else None

    def _analyze_signal(self, candles: list[Any]) -> tuple[TradeSignal, Any | None]:
        analyze_with_diagnostic = getattr(self.strategy, "analyze_with_diagnostic", None)
        if callable(analyze_with_diagnostic):
            signal, diagnostic = analyze_with_diagnostic(
                candles,
                self.symbol,
                self.timeframe,
            )
            return signal, diagnostic
        return self.strategy.analyze(candles, self.symbol, self.timeframe), None

    def _send_signal_diagnostic(
        self,
        *,
        signal: TradeSignal,
        diagnostic: Any | None,
        candle_ms: int,
    ) -> str:
        # Existing LINE diagnostic formatter is specific to BaselineStrategy.
        if self.strategy_id != "baseline" or diagnostic is None:
            return "not_available"
        if self.notifier is None:
            return "not_configured"
        try:
            self.notifier.send_text(
                format_signal_diagnostic_message(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    candle_ms=candle_ms,
                    signal_action=signal.action.value,
                    regime=diagnostic.regime.value,
                    price=diagnostic.price,
                    ema_fast=diagnostic.ema_fast,
                    ema_slow=diagnostic.ema_slow,
                    ema_bull_threshold=diagnostic.ema_bull_threshold,
                    rsi=diagnostic.rsi,
                    momentum_pct=diagnostic.momentum_pct,
                    atr=diagnostic.atr,
                    ema_trend_ok=diagnostic.ema_trend_ok,
                    price_above_ema_fast_ok=diagnostic.price_above_ema_fast_ok,
                    rsi_ok=diagnostic.rsi_ok,
                    momentum_ok=diagnostic.momentum_ok,
                    buy_ready=diagnostic.buy_ready,
                    blockers=list(diagnostic.blockers),
                )
            )
        except Exception as exc:
            return f"warning:{exc.__class__.__name__}"
        return "sent"

    @staticmethod
    def _attach_diagnostic(
        result: dict[str, Any],
        diagnostic: Any | None,
        line_status: str,
    ) -> dict[str, Any]:
        if diagnostic is not None and hasattr(diagnostic, "to_dict"):
            result["diagnostic"] = diagnostic.to_dict()
        result["diagnostic_line_notification"] = line_status
        return result

    def _send_open_notification(
        self,
        *,
        order: dict[str, Any],
        position: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> str:
        if self.notifier is None:
            return "not_configured"
        try:
            self.notifier.send_text(
                format_open_order_message(
                    symbol=self.symbol,
                    order_id=str(order["order_id"]),
                    side="buy",
                    account_balance_usdt=float(snapshot["quote_total"]),
                    estimated_portfolio_value_usdt=float(
                        snapshot["estimated_portfolio_value_quote"]
                    ),
                    entry_price=float(position["entry_price"]),
                    lot=float(position["quantity"]),
                    take_profit=(
                        float(position["take_profit"])
                        if position.get("take_profit") is not None
                        else None
                    ),
                    stop_loss=float(position["stop_loss"]),
                    binance_open_orders=int(snapshot["open_orders_count"]),
                    tracked_positions=self.position_store.count_active(),
                    strategy_id=self.strategy_id,
                )
            )
        except Exception as exc:
            return f"warning:{exc.__class__.__name__}"
        return "sent"

    def _send_exit_notification(
        self,
        *,
        reason: str,
        entry_position: dict[str, Any],
        exit_order: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> str:
        if self.notifier is None:
            return "not_configured"
        try:
            self.notifier.send_text(
                format_auto_exit_message(
                    reason=reason,
                    symbol=self.symbol,
                    entry_order_id=str(entry_position["order_id"]),
                    exit_order_id=str(exit_order["order_id"]),
                    account_balance_usdt=float(snapshot["quote_total"]),
                    estimated_portfolio_value_usdt=float(
                        snapshot["estimated_portfolio_value_quote"]
                    ),
                    entry_price=float(entry_position["entry_price"]),
                    exit_price=float(exit_order["average"]),
                    lot=float(exit_order["filled"]),
                    take_profit=(
                        float(entry_position["take_profit"])
                        if entry_position.get("take_profit") is not None
                        else None
                    ),
                    stop_loss=float(entry_position["stop_loss"]),
                    tracked_positions=self.position_store.count_active(),
                    strategy_id=self.strategy_id,
                )
            )
        except Exception as exc:
            return f"warning:{exc.__class__.__name__}"
        return "sent"

    def _levels_from_signal(
        self,
        signal: TradeSignal,
        fill_price: float,
    ) -> tuple[float | None, float]:
        if signal.entry_price is None or signal.stop_loss is None:
            raise AutoTradingHalted("approved BUY signal is missing entry or stop-loss")
        stop_pct = (signal.entry_price - signal.stop_loss) / signal.entry_price
        if not 0 < stop_pct < 1:
            raise AutoTradingHalted("approved BUY signal contains invalid stop-loss distance")
        stop_loss = fill_price * (1 - stop_pct)

        if signal.take_profit is None:
            if self.exit_mode == "fixed_tp_sl":
                raise AutoTradingHalted("fixed TP/SL strategy BUY is missing take-profit")
            return None, stop_loss

        target_pct = (signal.take_profit - signal.entry_price) / signal.entry_price
        if target_pct <= 0:
            raise AutoTradingHalted("approved BUY signal contains invalid take-profit distance")
        return fill_price * (1 + target_pct), stop_loss

    def _enter_position(
        self,
        *,
        signal: TradeSignal,
        candle_ms: int,
        notional_usdt: float,
    ) -> dict[str, Any]:
        self.state_store.begin_order_attempt(
            action="BUY",
            symbol=self.symbol,
            reason=f"{self.strategy_id.upper()}_BUY",
            candle_ms=candle_ms,
        )
        try:
            order = self.broker.place_market_order(self.symbol, "buy", notional_usdt)
        except Exception as exc:
            self.state_store.mark_order_uncertain(exc)
            raise AutoTradingHalted(
                "BUY submission failed after local attempt began; automation halted"
            ) from exc

        order_id = order.get("order_id")
        fill_price = order.get("average")
        quantity = order.get("sellable_quantity", order.get("filled"))
        if order_id is None or not fill_price or not quantity:
            error = RuntimeError("Binance Testnet BUY acknowledgement is missing fill data")
            self.state_store.mark_order_uncertain(error)
            raise AutoTradingHalted(str(error))
        self.state_store.mark_order_acknowledged(str(order_id))

        take_profit, stop_loss = self._levels_from_signal(signal, float(fill_price))
        position = self.position_store.add_long_position(
            order_id=str(order_id),
            symbol=self.symbol,
            entry_price=float(fill_price),
            quantity=float(quantity),
            take_profit=take_profit,
            stop_loss=stop_loss,
            strategy_id=self.strategy_id,
            exit_mode=self.exit_mode,
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
            "event": "BUY_FILLED",
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

    def _exit_position(
        self,
        *,
        position: dict[str, Any],
        reason: str,
        candle_ms: int,
    ) -> dict[str, Any]:
        self.state_store.begin_order_attempt(
            action="SELL",
            symbol=self.symbol,
            reason=reason,
            candle_ms=candle_ms,
        )
        try:
            order = self.broker.place_market_sell_quantity(
                self.symbol,
                float(position["quantity"]),
            )
        except Exception as exc:
            self.state_store.mark_order_uncertain(exc)
            raise AutoTradingHalted(
                "SELL submission failed after local attempt began; automation halted"
            ) from exc

        order_id = order.get("order_id")
        exit_price = order.get("average")
        if order_id is None or not exit_price:
            error = RuntimeError("Binance Testnet SELL acknowledgement is missing fill data")
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
        line_status = self._send_exit_notification(
            reason=reason,
            entry_position=position,
            exit_order=order,
            snapshot=snapshot,
        )
        self.state_store.finalize_order_attempt()
        self.state_store.mark_candle_processed(candle_ms)
        return {
            "event": "POSITION_CLOSED",
            "strategy_id": self.strategy_id,
            "reason": reason,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candle_ms": candle_ms,
            "entry_position": position,
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

        # Baseline exits are fixed TP/SL and may execute immediately on live price.
        if position is not None and self.exit_mode == "fixed_tp_sl":
            live_price = self.broker.current_price(self.symbol)
            take_profit = position.get("take_profit")
            if take_profit is not None and live_price >= float(take_profit):
                return self._exit_position(
                    position=position,
                    reason="TP_HIT",
                    candle_ms=candle_ms,
                )
            if live_price <= float(position["stop_loss"]):
                return self._exit_position(
                    position=position,
                    reason="SL_HIT",
                    candle_ms=candle_ms,
                )

        if self.state_store.last_processed_candle_ms() == candle_ms:
            return {
                "event": "WAIT_NEXT_CANDLE",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
                "tracked_positions": self.position_store.count_active(),
            }

        signal, diagnostic = self._analyze_signal(candles)
        diagnostic_line_status = self._send_signal_diagnostic(
            signal=signal,
            diagnostic=diagnostic,
            candle_ms=candle_ms,
        )

        # Dynamic EMA strategy updates its displayed/risk reference once per closed candle.
        if (
            position is not None
            and self.exit_mode == "close_below_ema50"
            and signal.stop_loss is not None
        ):
            position = self.position_store.update_stop_loss(
                str(position["order_id"]),
                float(signal.stop_loss),
            )

        if position is not None:
            if signal.action == TradeAction.EXIT:
                reason = (
                    "EMA50_CLOSE_EXIT"
                    if self.exit_mode == "close_below_ema50"
                    else "STRATEGY_EXIT"
                )
                result = self._exit_position(
                    position=position,
                    reason=reason,
                    candle_ms=candle_ms,
                )
                result["signal"] = signal.model_dump(mode="json")
                return self._attach_diagnostic(result, diagnostic, diagnostic_line_status)
            self.state_store.mark_candle_processed(candle_ms)
            result = {
                "event": "POSITION_HELD",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
                "signal": signal.model_dump(mode="json"),
                "position": position,
                "tracked_positions": self.position_store.count_active(),
            }
            return self._attach_diagnostic(result, diagnostic, diagnostic_line_status)

        if signal.action != TradeAction.BUY:
            self.state_store.mark_candle_processed(candle_ms)
            result = {
                "event": "NO_TRADE",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
                "signal": signal.model_dump(mode="json"),
            }
            return self._attach_diagnostic(result, diagnostic, diagnostic_line_status)

        snapshot = self.broker.account_snapshot(self.symbol)
        equity = float(snapshot["estimated_portfolio_value_quote"])
        risk = self.risk_engine.evaluate_entry(signal, equity)
        if not risk.approved:
            self.state_store.mark_candle_processed(candle_ms)
            result = {
                "event": "RISK_BLOCKED",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
                "signal": signal.model_dump(mode="json"),
                "risk": risk.model_dump(mode="json"),
            }
            return self._attach_diagnostic(result, diagnostic, diagnostic_line_status)

        notional = min(
            self.entry_notional_usdt,
            float(risk.notional),
            self.broker.max_order_notional_usdt,
        )
        market = self.broker._load_market(self.symbol)
        market_minimum = self.broker._min_notional(market)
        minimum_notional = float(market_minimum) if market_minimum is not None else 0.0
        if notional < minimum_notional:
            self.state_store.mark_candle_processed(candle_ms)
            result = {
                "event": "RISK_BLOCKED",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
                "signal": signal.model_dump(mode="json"),
                "risk": risk.model_dump(mode="json"),
                "reason": (
                    f"approved notional {notional:.4f} is below exchange minimum "
                    f"{minimum_notional:.4f}"
                ),
            }
            return self._attach_diagnostic(result, diagnostic, diagnostic_line_status)
        if float(snapshot["quote_free"]) < notional:
            self.state_store.mark_candle_processed(candle_ms)
            result = {
                "event": "RISK_BLOCKED",
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_ms": candle_ms,
                "signal": signal.model_dump(mode="json"),
                "risk": risk.model_dump(mode="json"),
                "reason": "insufficient free USDT Testnet balance",
            }
            return self._attach_diagnostic(result, diagnostic, diagnostic_line_status)

        result = self._enter_position(
            signal=signal,
            candle_ms=candle_ms,
            notional_usdt=notional,
        )
        return self._attach_diagnostic(result, diagnostic, diagnostic_line_status)
