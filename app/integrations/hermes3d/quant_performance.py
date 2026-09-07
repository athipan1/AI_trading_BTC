from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class QuantPerformanceProjection:
    """Read-only quant metrics derived from reconciled PositionStore records."""

    @staticmethod
    def _float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @classmethod
    def _reconciled_closed(cls, positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            item
            for item in positions
            if item.get("status") == "CLOSED"
            and item.get("reconciliation_status") == "RECONCILED"
            and cls._float(item.get("net_realized_pnl")) is not None
        ]

    @classmethod
    def _initial_risk_usdt(cls, position: dict[str, Any]) -> tuple[float | None, bool]:
        entry = cls._float(position.get("entry_fill_price"))
        if entry is None:
            entry = cls._float(position.get("entry_price"))
        quantity = cls._float(position.get("entry_filled_quantity"))
        if quantity is None:
            quantity = cls._float(position.get("quantity"))

        initial_stop = cls._float(position.get("initial_stop_loss"))
        used_fallback = False
        if initial_stop is None:
            initial_stop = cls._float(position.get("stop_loss"))
            used_fallback = initial_stop is not None

        if entry is None or quantity is None or initial_stop is None:
            return None, used_fallback
        risk = abs(entry - initial_stop) * quantity
        if risk <= 0:
            return None, used_fallback
        return risk, used_fallback

    @classmethod
    def _holding_seconds(cls, position: dict[str, Any]) -> float | None:
        opened = cls._timestamp(position.get("created_at"))
        closed = cls._timestamp(position.get("closed_at"))
        if opened is None or closed is None or closed < opened:
            return None
        return (closed - opened).total_seconds()

    @classmethod
    def _slippage_cost_usdt(cls, position: dict[str, Any]) -> float | None:
        entry_reference = cls._float(position.get("entry_price"))
        entry_actual = cls._float(position.get("entry_fill_price"))
        entry_qty = cls._float(position.get("entry_filled_quantity"))
        exit_reference = cls._float(position.get("exit_price"))
        exit_actual = cls._float(position.get("exit_fill_price"))
        exit_qty = cls._float(position.get("exit_filled_quantity"))
        side = str(position.get("side", "buy")).lower()

        values = (
            entry_reference,
            entry_actual,
            entry_qty,
            exit_reference,
            exit_actual,
            exit_qty,
        )
        if any(value is None for value in values):
            return None
        assert entry_reference is not None
        assert entry_actual is not None
        assert entry_qty is not None
        assert exit_reference is not None
        assert exit_actual is not None
        assert exit_qty is not None

        if side == "buy":
            entry_cost = (entry_actual - entry_reference) * entry_qty
            exit_cost = (exit_reference - exit_actual) * exit_qty
        elif side == "sell":
            entry_cost = (entry_reference - entry_actual) * entry_qty
            exit_cost = (exit_actual - exit_reference) * exit_qty
        else:
            return None
        return entry_cost + exit_cost

    @classmethod
    def _path_excursion(cls, position: dict[str, Any]) -> dict[str, float] | None:
        entry = cls._float(position.get("entry_fill_price"))
        if entry is None:
            entry = cls._float(position.get("entry_price"))
        quantity = cls._float(position.get("entry_filled_quantity"))
        if quantity is None:
            quantity = cls._float(position.get("quantity"))
        highest = cls._float(position.get("trade_path_highest_price"))
        lowest = cls._float(position.get("trade_path_lowest_price"))
        risk, used_fallback = cls._initial_risk_usdt(position)
        if (
            entry is None
            or quantity is None
            or highest is None
            or lowest is None
            or risk is None
            or used_fallback
        ):
            return None

        side = str(position.get("side", "buy")).lower()
        if side == "buy":
            mfe_usdt = max(0.0, (highest - entry) * quantity)
            mae_usdt = min(0.0, (lowest - entry) * quantity)
        elif side == "sell":
            mfe_usdt = max(0.0, (entry - lowest) * quantity)
            mae_usdt = min(0.0, (entry - highest) * quantity)
        else:
            return None
        return {
            "mfe_usdt": mfe_usdt,
            "mae_usdt": mae_usdt,
            "mfe_r": mfe_usdt / risk,
            "mae_r": mae_usdt / risk,
        }

    @classmethod
    def _equity_metrics(cls, positions: list[dict[str, Any]]) -> dict[str, Any]:
        sortable: list[tuple[datetime, str, float]] = []
        for item in positions:
            closed_at = cls._timestamp(item.get("closed_at"))
            pnl = cls._float(item.get("net_realized_pnl"))
            if closed_at is None or pnl is None:
                continue
            sortable.append((closed_at, str(item.get("order_id", "")), pnl))
        sortable.sort(key=lambda value: (value[0], value[1]))

        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        curve: list[dict[str, Any]] = []
        for closed_at, order_id, pnl in sortable:
            cumulative += pnl
            peak = max(peak, cumulative)
            drawdown = max(0.0, peak - cumulative)
            max_drawdown = max(max_drawdown, drawdown)
            curve.append(
                {
                    "closed_at": closed_at.isoformat(),
                    "order_id": order_id,
                    "trade_pnl_usdt": round(pnl, 8),
                    "cumulative_pnl_usdt": round(cumulative, 8),
                    "drawdown_usdt": round(drawdown, 8),
                }
            )

        return {
            "basis": "zero_based_cumulative_net_realized_pnl",
            "points": curve,
            "ending_pnl_usdt": round(cumulative, 8),
            "max_drawdown_usdt": round(max_drawdown, 8),
        }

    @classmethod
    def summarize(cls, positions: list[dict[str, Any]]) -> dict[str, Any]:
        closed_count = sum(item.get("status") == "CLOSED" for item in positions)
        reconciled = cls._reconciled_closed(positions)
        pnls = [float(item["net_realized_pnl"]) for item in reconciled]
        wins = [value for value in pnls if value > 0]
        losses = [value for value in pnls if value < 0]

        r_multiples: list[float] = []
        risk_fallback_count = 0
        holding_seconds: list[float] = []
        slippage_costs: list[float] = []
        mae_usdt_values: list[float] = []
        mfe_usdt_values: list[float] = []
        mae_r_values: list[float] = []
        mfe_r_values: list[float] = []
        fees = 0.0
        fee_complete = True
        gross_abs_pnl = 0.0

        for item in reconciled:
            pnl = float(item["net_realized_pnl"])
            risk, used_fallback = cls._initial_risk_usdt(item)
            if risk is not None:
                r_multiples.append(pnl / risk)
                risk_fallback_count += int(used_fallback)

            path = cls._path_excursion(item)
            if path is not None:
                mae_usdt_values.append(path["mae_usdt"])
                mfe_usdt_values.append(path["mfe_usdt"])
                mae_r_values.append(path["mae_r"])
                mfe_r_values.append(path["mfe_r"])

            holding = cls._holding_seconds(item)
            if holding is not None:
                holding_seconds.append(holding)

            slippage_cost = cls._slippage_cost_usdt(item)
            if slippage_cost is not None:
                slippage_costs.append(slippage_cost)

            entry_fee = cls._float(item.get("entry_commission_quote_equivalent"))
            exit_fee = cls._float(item.get("exit_commission_quote_equivalent"))
            if entry_fee is None or exit_fee is None:
                fee_complete = False
            else:
                fees += entry_fee + exit_fee

            gross_pnl = cls._float(item.get("gross_realized_pnl"))
            if gross_pnl is not None:
                gross_abs_pnl += abs(gross_pnl)

        expectancy = sum(pnls) / len(pnls) if pnls else None
        average_win = sum(wins) / len(wins) if wins else None
        average_loss = sum(losses) / len(losses) if losses else None
        payoff_ratio = (
            average_win / abs(average_loss)
            if average_win is not None and average_loss is not None and average_loss != 0
            else None
        )
        average_r = sum(r_multiples) / len(r_multiples) if r_multiples else None
        average_holding = (
            sum(holding_seconds) / len(holding_seconds) if holding_seconds else None
        )
        slippage_total = sum(slippage_costs) if slippage_costs else None
        fee_drag_pct = (
            (fees / gross_abs_pnl) * 100 if fee_complete and gross_abs_pnl > 0 else None
        )

        return {
            "basis": "exchange_reconciled_closed_trades_only",
            "closed_trades_seen": closed_count,
            "evaluated_trades": len(reconciled),
            "excluded_unreconciled_trades": closed_count - len(reconciled),
            "expectancy_usdt_per_trade": round(expectancy, 8) if expectancy is not None else None,
            "average_win_usdt": round(average_win, 8) if average_win is not None else None,
            "average_loss_usdt": round(average_loss, 8) if average_loss is not None else None,
            "payoff_ratio": round(payoff_ratio, 6) if payoff_ratio is not None else None,
            "average_r_multiple": round(average_r, 6) if average_r is not None else None,
            "r_multiple_coverage_pct": round((len(r_multiples) / len(reconciled)) * 100, 4)
            if reconciled
            else 0.0,
            "r_multiple_stop_fallback_trades": risk_fallback_count,
            "average_mae_usdt": round(sum(mae_usdt_values) / len(mae_usdt_values), 8)
            if mae_usdt_values
            else None,
            "average_mfe_usdt": round(sum(mfe_usdt_values) / len(mfe_usdt_values), 8)
            if mfe_usdt_values
            else None,
            "average_mae_r": round(sum(mae_r_values) / len(mae_r_values), 6)
            if mae_r_values
            else None,
            "average_mfe_r": round(sum(mfe_r_values) / len(mfe_r_values), 6)
            if mfe_r_values
            else None,
            "mae_mfe_coverage_pct": round((len(mae_r_values) / len(reconciled)) * 100, 4)
            if reconciled
            else 0.0,
            "average_holding_seconds": round(average_holding, 3)
            if average_holding is not None
            else None,
            "holding_time_coverage_pct": round((len(holding_seconds) / len(reconciled)) * 100, 4)
            if reconciled
            else 0.0,
            "commission_usdt": round(fees, 8) if fee_complete and reconciled else None,
            "fee_drag_pct_of_absolute_gross_pnl": round(fee_drag_pct, 6)
            if fee_drag_pct is not None
            else None,
            "slippage_cost_usdt": round(slippage_total, 8)
            if slippage_total is not None
            else None,
            "slippage_cost_coverage_pct": round((len(slippage_costs) / len(reconciled)) * 100, 4)
            if reconciled
            else 0.0,
            "equity": cls._equity_metrics(reconciled),
        }

    @classmethod
    def by_strategy(cls, positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        strategy_ids = sorted(
            {
                str(item.get("strategy_id", "baseline")).lower()
                for item in positions
                if item.get("strategy_id") or item.get("order_id")
            }
        )
        return {
            strategy_id: cls.summarize(
                [
                    item
                    for item in positions
                    if str(item.get("strategy_id", "baseline")).lower() == strategy_id
                ]
            )
            for strategy_id in strategy_ids
        }

    @classmethod
    def by_market_regime(cls, positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        regimes = sorted(
            {
                str(item.get("entry_market_regime"))
                for item in positions
                if item.get("entry_market_regime")
            }
        )
        return {
            regime: cls.summarize(
                [item for item in positions if str(item.get("entry_market_regime")) == regime]
            )
            for regime in regimes
        }

    @classmethod
    def by_strategy_and_market_regime(
        cls,
        positions: list[dict[str, Any]],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        strategy_ids = sorted(
            {
                str(item.get("strategy_id", "baseline")).lower()
                for item in positions
                if item.get("strategy_id") or item.get("order_id")
            }
        )
        result: dict[str, dict[str, dict[str, Any]]] = {}
        for strategy_id in strategy_ids:
            strategy_positions = [
                item
                for item in positions
                if str(item.get("strategy_id", "baseline")).lower() == strategy_id
            ]
            regimes = sorted(
                {
                    str(item.get("entry_market_regime"))
                    for item in strategy_positions
                    if item.get("entry_market_regime")
                }
            )
            result[strategy_id] = {
                regime: cls.summarize(
                    [
                        item
                        for item in strategy_positions
                        if str(item.get("entry_market_regime")) == regime
                    ]
                )
                for regime in regimes
            }
        return result

    @classmethod
    def data_availability(cls, positions: list[dict[str, Any]]) -> dict[str, Any]:
        reconciled = cls._reconciled_closed(positions)
        total = len(reconciled)
        initial_stop_count = sum(
            cls._float(item.get("initial_stop_loss")) is not None
            and item.get("initial_stop_loss_source") == "entry_snapshot"
            for item in reconciled
        )
        initial_risk_count = sum(
            cls._float(item.get("initial_risk_price_distance")) is not None
            and cls._float(item.get("initial_risk_usdt")) is not None
            and item.get("initial_risk_source") == "entry_snapshot"
            for item in reconciled
        )
        path_count = sum(cls._path_excursion(item) is not None for item in reconciled)
        regime_count = sum(bool(item.get("entry_market_regime")) for item in reconciled)

        def coverage(count: int) -> float:
            return round((count / total) * 100, 4) if total else 0.0

        return {
            "advanced_metrics_basis": "exchange_reconciled_closed_trades_only",
            "trade_path_basis": "runner_live_price_samples",
            "initial_stop_loss_coverage_pct": coverage(initial_stop_count),
            "initial_risk_snapshot_coverage_pct": coverage(initial_risk_count),
            "mae_mfe_available": path_count > 0,
            "mae_mfe_coverage_pct": coverage(path_count),
            "mae_mfe_reason": None
            if path_count == total and total
            else "prospective_trade_path_samples_required",
            "market_regime_available": regime_count > 0,
            "market_regime_coverage_pct": coverage(regime_count),
            "market_regime_reason": None
            if regime_count == total and total
            else "prospective_entry_regime_snapshot_required",
        }
