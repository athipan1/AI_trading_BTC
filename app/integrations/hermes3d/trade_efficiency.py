from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any

from app.integrations.hermes3d.quant_performance import QuantPerformanceProjection


class TradeEfficiencyProjection:
    """Read-only diagnostics derived from reconciled Phase 4.2 trade-path data."""

    @classmethod
    def _trade_efficiency(cls, position: dict[str, Any]) -> dict[str, Any] | None:
        pnl = QuantPerformanceProjection._float(position.get("net_realized_pnl"))
        risk, used_fallback = QuantPerformanceProjection._initial_risk_usdt(position)
        path = QuantPerformanceProjection._path_excursion(position)
        if pnl is None or risk is None or used_fallback or path is None:
            return None

        realized_r = pnl / risk
        mfe_r = path["mfe_r"]
        mae_r = path["mae_r"]
        capture_ratio = realized_r / mfe_r if mfe_r > 0 else None
        giveback_r = mfe_r - realized_r
        mae_utilization_r = abs(mae_r)

        if mfe_r >= 1.5 and capture_ratio is not None and capture_ratio >= 0.60:
            diagnostic = "GOOD_ENTRY_GOOD_EXIT"
        elif mfe_r >= 1.5 and capture_ratio is not None and capture_ratio < 0.40:
            diagnostic = "GOOD_ENTRY_WEAK_EXIT"
        elif mfe_r < 0.5 and mae_utilization_r >= 0.5:
            diagnostic = "WEAK_ENTRY"
        elif mae_utilization_r >= 0.8:
            diagnostic = "STOP_PRESSURE"
        elif mfe_r < 0.5 and mae_utilization_r < 0.5:
            diagnostic = "LOW_OPPORTUNITY"
        else:
            diagnostic = "UNCLASSIFIED"

        return {
            "realized_r": realized_r,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "mfe_capture_ratio": capture_ratio,
            "profit_giveback_r": giveback_r,
            "mae_utilization_r": mae_utilization_r,
            "winner_to_loser_reversal": mfe_r >= 1.0 and realized_r <= 0,
            "stop_pressure": mae_utilization_r >= 0.8,
            "diagnostic": diagnostic,
        }

    @staticmethod
    def _average(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    @staticmethod
    def _round(value: float | None, digits: int = 6) -> float | None:
        return round(value, digits) if value is not None else None

    @classmethod
    def summarize(cls, positions: list[dict[str, Any]]) -> dict[str, Any]:
        reconciled = QuantPerformanceProjection._reconciled_closed(positions)
        diagnostics = [
            metric
            for item in reconciled
            if (metric := cls._trade_efficiency(item)) is not None
        ]
        realized = [float(item["realized_r"]) for item in diagnostics]
        mfe = [float(item["mfe_r"]) for item in diagnostics]
        mae = [float(item["mae_r"]) for item in diagnostics]
        captures = [
            float(item["mfe_capture_ratio"])
            for item in diagnostics
            if item["mfe_capture_ratio"] is not None
        ]
        givebacks = [float(item["profit_giveback_r"]) for item in diagnostics]
        mae_utilization = [float(item["mae_utilization_r"]) for item in diagnostics]
        labels = Counter(str(item["diagnostic"]) for item in diagnostics)
        reversals = sum(bool(item["winner_to_loser_reversal"]) for item in diagnostics)
        stop_pressure = sum(bool(item["stop_pressure"]) for item in diagnostics)
        evaluated = len(diagnostics)
        total = len(reconciled)

        def coverage(count: int) -> float:
            return round((count / total) * 100, 4) if total else 0.0

        def rate(count: int) -> float:
            return round((count / evaluated) * 100, 4) if evaluated else 0.0

        return {
            "basis": "exchange_reconciled_closed_trades_with_phase42_trade_path",
            "reconciled_trades_seen": total,
            "evaluated_trades": evaluated,
            "excluded_missing_trade_path": total - evaluated,
            "trade_efficiency_coverage_pct": coverage(evaluated),
            "capture_ratio_coverage_pct": coverage(len(captures)),
            "average_realized_r": cls._round(cls._average(realized)),
            "median_realized_r": cls._round(median(realized) if realized else None),
            "average_mfe_r": cls._round(cls._average(mfe)),
            "median_mfe_r": cls._round(median(mfe) if mfe else None),
            "average_mae_r": cls._round(cls._average(mae)),
            "median_mae_r": cls._round(median(mae) if mae else None),
            "average_mfe_capture_ratio": cls._round(cls._average(captures)),
            "median_mfe_capture_ratio": cls._round(median(captures) if captures else None),
            "average_profit_giveback_r": cls._round(cls._average(givebacks)),
            "median_profit_giveback_r": cls._round(median(givebacks) if givebacks else None),
            "average_mae_utilization_r": cls._round(cls._average(mae_utilization)),
            "winner_to_loser_reversal_rate_pct": rate(reversals),
            "stop_pressure_rate_pct": rate(stop_pressure),
            "diagnostic_counts": dict(sorted(labels.items())),
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
        result: dict[str, dict[str, dict[str, Any]]] = {}
        for strategy_id, strategy_summary in cls.by_strategy(positions).items():
            del strategy_summary
            strategy_positions = [
                item
                for item in positions
                if str(item.get("strategy_id", "baseline")).lower() == strategy_id
            ]
            result[strategy_id] = cls.by_market_regime(strategy_positions)
        return result
