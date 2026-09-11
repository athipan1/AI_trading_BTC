from __future__ import annotations

from typing import Any

from app.integrations.hermes3d.quant_performance import QuantPerformanceProjection


class ProductionAnalyticsReadinessProjection:
    """Read-only quality gate for production quant-research cohorts."""

    ADVANCED_COVERAGE_TARGET_PCT = 95.0
    MIN_RESEARCH_TRADES = 30

    @classmethod
    def _is_reconciled_closed(cls, item: dict[str, Any]) -> bool:
        return (
            item.get("status") == "CLOSED"
            and item.get("reconciliation_status") == "RECONCILED"
            and QuantPerformanceProjection._float(item.get("net_realized_pnl")) is not None
        )

    @classmethod
    def _has_entry_risk_snapshot(cls, item: dict[str, Any]) -> bool:
        return (
            QuantPerformanceProjection._float(item.get("initial_stop_loss")) is not None
            and item.get("initial_stop_loss_source") == "entry_snapshot"
            and QuantPerformanceProjection._float(item.get("initial_risk_price_distance")) is not None
            and QuantPerformanceProjection._float(item.get("initial_risk_usdt")) is not None
            and item.get("initial_risk_source") == "entry_snapshot"
        )

    @classmethod
    def qualification_failures(cls, item: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        if not cls._is_reconciled_closed(item):
            failures.append("NOT_RECONCILED_CLOSED")
        if not cls._has_entry_risk_snapshot(item):
            failures.append("MISSING_INITIAL_RISK_SNAPSHOT")
        if not item.get("entry_market_regime"):
            failures.append("MISSING_ENTRY_MARKET_REGIME")
        if QuantPerformanceProjection._path_excursion(item) is None:
            failures.append("MISSING_TRADE_PATH")
        return failures

    @classmethod
    def is_qualified_trade(cls, item: dict[str, Any]) -> bool:
        return not cls.qualification_failures(item)

    @classmethod
    def _is_qualified(cls, item: dict[str, Any]) -> bool:
        return cls.is_qualified_trade(item)

    @staticmethod
    def _coverage(count: int, total: int) -> float:
        return round((count / total) * 100, 4) if total else 0.0

    @classmethod
    def summarize(cls, positions: list[dict[str, Any]]) -> dict[str, Any]:
        closed = [item for item in positions if item.get("status") == "CLOSED"]
        reconciled = [item for item in closed if cls._is_reconciled_closed(item)]
        qualified = [item for item in reconciled if cls.is_qualified_trade(item)]

        total_closed = len(closed)
        total_reconciled = len(reconciled)
        risk_count = sum(cls._has_entry_risk_snapshot(item) for item in reconciled)
        regime_count = sum(bool(item.get("entry_market_regime")) for item in reconciled)
        path_count = sum(
            QuantPerformanceProjection._path_excursion(item) is not None for item in reconciled
        )

        reconciliation_pct = cls._coverage(total_reconciled, total_closed)
        risk_pct = cls._coverage(risk_count, total_reconciled)
        regime_pct = cls._coverage(regime_count, total_reconciled)
        path_pct = cls._coverage(path_count, total_reconciled)
        qualified_pct = cls._coverage(len(qualified), total_reconciled)

        accounting_ready = total_closed > 0 and reconciliation_pct == 100.0
        advanced_ready = (
            total_reconciled > 0
            and min(risk_pct, regime_pct, path_pct) >= cls.ADVANCED_COVERAGE_TARGET_PCT
        )
        research_ready = advanced_ready and len(qualified) >= cls.MIN_RESEARCH_TRADES

        return {
            "basis": "production_position_store_read_only",
            "closed_trades": total_closed,
            "reconciled_closed_trades": total_reconciled,
            "qualified_trades": len(qualified),
            "legacy_or_unqualified_reconciled_trades": total_reconciled - len(qualified),
            "coverage": {
                "reconciliation_pct": reconciliation_pct,
                "initial_risk_snapshot_pct": risk_pct,
                "market_regime_pct": regime_pct,
                "trade_path_mae_mfe_pct": path_pct,
                "qualified_cohort_pct": qualified_pct,
            },
            "thresholds": {
                "accounting_reconciliation_pct": 100.0,
                "advanced_metrics_pct": cls.ADVANCED_COVERAGE_TARGET_PCT,
                "minimum_research_trades": cls.MIN_RESEARCH_TRADES,
            },
            "readiness": {
                "pipeline": "READY" if total_reconciled > 0 else "NO_RECONCILED_TRADES",
                "accounting": "READY" if accounting_ready else "NOT_READY",
                "data_quality": "READY" if advanced_ready else "NOT_READY",
                "research_sample": "SUFFICIENT"
                if len(qualified) >= cls.MIN_RESEARCH_TRADES
                else "LOW",
                "research": "READY" if research_ready else "NOT_READY",
            },
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
