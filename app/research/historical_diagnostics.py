from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from statistics import mean, median
from typing import Any


class HistoricalResearchDiagnostics:
    """Read-only coverage and distribution diagnostics for historical research trades."""

    SCHEMA_VERSION = "historical_research_diagnostics_v1"

    @staticmethod
    def _float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @staticmethod
    def _year(value: Any) -> str | None:
        if value is None:
            return None
        try:
            return str(datetime.fromisoformat(str(value).replace("Z", "+00:00")).year)
        except ValueError:
            return None

    @classmethod
    def _summary(cls, values: list[float]) -> dict[str, float | None]:
        if not values:
            return {"mean": None, "median": None, "min": None, "max": None}
        return {
            "mean": mean(values),
            "median": median(values),
            "min": min(values),
            "max": max(values),
        }

    @classmethod
    def build(cls, trades: list[dict[str, Any]]) -> dict[str, Any]:
        strategy_counts: Counter[str] = Counter()
        year_counts: Counter[str] = Counter()
        regime_counts: Counter[str] = Counter()
        side_counts: Counter[str] = Counter()
        order_ids: list[str] = []
        realized_r: list[float] = []
        mae_r: list[float] = []
        mfe_r: list[float] = []
        holding_seconds: list[float] = []
        wins = 0
        losses = 0
        breakeven = 0
        invalid_rows = 0

        for trade in trades:
            order_id = str(trade.get("order_id") or "").strip()
            strategy_id = str(trade.get("strategy_id") or "").strip()
            regime = str(trade.get("entry_market_regime") or "").strip()
            side = str(trade.get("side") or "").strip().lower()
            year = cls._year(trade.get("created_at"))
            r_value = cls._float(trade.get("realized_r"))
            mae_value = cls._float(trade.get("mae_r"))
            mfe_value = cls._float(trade.get("mfe_r"))
            holding_value = cls._float(trade.get("holding_seconds"))

            if not order_id or not strategy_id or not regime or side not in {"buy", "sell"} or year is None:
                invalid_rows += 1
                continue

            order_ids.append(order_id)
            strategy_counts[strategy_id] += 1
            year_counts[year] += 1
            regime_counts[regime] += 1
            side_counts[side] += 1

            if r_value is not None:
                realized_r.append(r_value)
                if r_value > 0:
                    wins += 1
                elif r_value < 0:
                    losses += 1
                else:
                    breakeven += 1
            if mae_value is not None:
                mae_r.append(mae_value)
            if mfe_value is not None:
                mfe_r.append(mfe_value)
            if holding_value is not None and holding_value >= 0:
                holding_seconds.append(holding_value)

        duplicate_order_ids = sum(
            count - 1 for count in Counter(order_ids).values() if count > 1
        )
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "read_only": True,
            "sample_size": len(trades),
            "valid_rows": len(trades) - invalid_rows,
            "invalid_rows": invalid_rows,
            "duplicate_order_ids": duplicate_order_ids,
            "coverage": {
                "strategies": dict(sorted(strategy_counts.items())),
                "years": dict(sorted(year_counts.items())),
                "regimes": dict(sorted(regime_counts.items())),
                "sides": dict(sorted(side_counts.items())),
                "calendar_year_count": len(year_counts),
                "regime_count": len(regime_counts),
            },
            "outcomes": {
                "wins": wins,
                "losses": losses,
                "breakeven": breakeven,
            },
            "distributions": {
                "realized_r": cls._summary(realized_r),
                "mae_r": cls._summary(mae_r),
                "mfe_r": cls._summary(mfe_r),
                "holding_seconds": cls._summary(holding_seconds),
            },
        }
