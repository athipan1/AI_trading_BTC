"""Pure-Python, selection-level realized-R metrics shared by frozen OOS studies.

Returns the Phase 5.6 metric contract. No model fitting, NumPy, or scikit-learn.
"""

from __future__ import annotations

from collections.abc import Sequence


def realized_r_selection_metrics(
    realized: Sequence[float],
    mask: Sequence[bool],
) -> dict[str, float | int | None]:
    """Measure chronologically ordered realized-R samples under a selection mask."""
    if len(realized) != len(mask):
        raise ValueError("realized and selection mask must have identical lengths")
    selected = [float(value) for value, take in zip(realized, mask, strict=True) if bool(take)]
    count = len(selected)
    if count == 0:
        return {
            "available_signals": len(realized),
            "trade_count": 0,
            "selection_rate_pct": 0.0,
            "win_rate_pct": None,
            "expectancy_r": None,
            "total_realized_r": 0.0,
            "profit_factor": None,
            "max_drawdown_r": 0.0,
        }
    gross_profit = sum(value for value in selected if value > 0)
    gross_loss = abs(sum(value for value in selected if value < 0))
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in selected:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "available_signals": len(realized),
        "trade_count": count,
        "selection_rate_pct": count / len(realized) * 100,
        "win_rate_pct": sum(value > 0 for value in selected) / count * 100,
        "expectancy_r": sum(selected) / count,
        "total_realized_r": sum(selected),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "max_drawdown_r": max_drawdown,
    }
