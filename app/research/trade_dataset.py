from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any, Literal

from app.integrations.hermes3d.production_analytics_readiness import (
    ProductionAnalyticsReadinessProjection,
)
from app.integrations.hermes3d.quant_performance import QuantPerformanceProjection
from app.integrations.hermes3d.trade_efficiency import TradeEfficiencyProjection

ResearchSource = Literal["production", "historical", "combined"]


class ResearchTradeDatasetProjection:
    """Build a versioned research dataset from production and/or historical trades."""

    SCHEMA_VERSION = "research_trade_schema_v2"
    BASIS = "qualified_production_and_historical_replay_trades"

    METADATA_COLUMNS = (
        "order_id",
        "strategy_id",
        "symbol",
        "side",
        "opened_at",
        "closed_at",
        "exit_reason",
        "data_origin",
    )
    FEATURE_COLUMNS = (
        "entry_price",
        "entry_fill_price",
        "quantity",
        "initial_stop_loss",
        "initial_risk_price_distance",
        "initial_risk_usdt",
        "entry_market_regime",
    )
    TARGET_COLUMNS = (
        "exit_price",
        "exit_fill_price",
        "holding_seconds",
        "trade_path_highest_price",
        "trade_path_lowest_price",
        "trade_path_observation_count",
        "mae_usdt",
        "mfe_usdt",
        "mae_r",
        "mfe_r",
        "gross_realized_pnl",
        "net_realized_pnl",
        "realized_r",
        "entry_commission_usdt",
        "exit_commission_usdt",
        "total_commission_usdt",
        "slippage_cost_usdt",
        "mfe_capture_ratio",
        "profit_giveback_r",
        "mae_utilization_r",
        "trade_diagnostic",
    )
    COLUMNS = METADATA_COLUMNS + FEATURE_COLUMNS + TARGET_COLUMNS

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _matches_filters(
        item: dict[str, Any],
        *,
        strategy_id: str | None,
        regime: str | None,
    ) -> bool:
        item_strategy = str(item.get("strategy_id", "baseline")).lower()
        item_regime = str(item.get("entry_market_regime", "")).upper()
        if strategy_id is not None and item_strategy != strategy_id:
            return False
        if regime is not None and item_regime != regime:
            return False
        return True

    @classmethod
    def _row_validation_failures(cls, item: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        if QuantPerformanceProjection._holding_seconds(item) is None:
            failures.append("INVALID_HOLDING_PERIOD")
        if QuantPerformanceProjection._float(item.get("entry_fill_price")) is None:
            failures.append("MISSING_ENTRY_FILL_PRICE")
        if QuantPerformanceProjection._float(item.get("exit_fill_price")) is None:
            failures.append("MISSING_EXIT_FILL_PRICE")
        return failures

    @classmethod
    def _production_row(cls, item: dict[str, Any]) -> dict[str, Any]:
        path = QuantPerformanceProjection._path_excursion(item)
        efficiency = TradeEfficiencyProjection._trade_efficiency(item)
        risk, used_fallback = QuantPerformanceProjection._initial_risk_usdt(item)
        if path is None or efficiency is None or risk is None or used_fallback:
            raise ValueError("qualified research trade is missing canonical quant metrics")

        entry_fee = QuantPerformanceProjection._float(
            item.get("entry_commission_quote_equivalent")
        )
        exit_fee = QuantPerformanceProjection._float(
            item.get("exit_commission_quote_equivalent")
        )
        total_fee = entry_fee + exit_fee if entry_fee is not None and exit_fee is not None else None
        quantity = QuantPerformanceProjection._float(item.get("entry_filled_quantity"))
        if quantity is None:
            quantity = QuantPerformanceProjection._float(item.get("quantity"))

        return {
            "order_id": str(item.get("order_id", "")),
            "strategy_id": str(item.get("strategy_id", "baseline")).lower(),
            "symbol": str(item.get("symbol", "")).upper(),
            "side": str(item.get("side", "")).lower(),
            "opened_at": item.get("created_at"),
            "closed_at": item.get("closed_at"),
            "exit_reason": item.get("exit_reason"),
            "data_origin": "production",
            "entry_price": QuantPerformanceProjection._float(item.get("entry_price")),
            "entry_fill_price": QuantPerformanceProjection._float(item.get("entry_fill_price")),
            "quantity": quantity,
            "initial_stop_loss": QuantPerformanceProjection._float(item.get("initial_stop_loss")),
            "initial_risk_price_distance": QuantPerformanceProjection._float(
                item.get("initial_risk_price_distance")
            ),
            "initial_risk_usdt": risk,
            "entry_market_regime": item.get("entry_market_regime"),
            "exit_price": QuantPerformanceProjection._float(item.get("exit_price")),
            "exit_fill_price": QuantPerformanceProjection._float(item.get("exit_fill_price")),
            "holding_seconds": QuantPerformanceProjection._holding_seconds(item),
            "trade_path_highest_price": QuantPerformanceProjection._float(
                item.get("trade_path_highest_price")
            ),
            "trade_path_lowest_price": QuantPerformanceProjection._float(
                item.get("trade_path_lowest_price")
            ),
            "trade_path_observation_count": int(item.get("trade_path_observation_count") or 0),
            "mae_usdt": path["mae_usdt"],
            "mfe_usdt": path["mfe_usdt"],
            "mae_r": path["mae_r"],
            "mfe_r": path["mfe_r"],
            "gross_realized_pnl": QuantPerformanceProjection._float(item.get("gross_realized_pnl")),
            "net_realized_pnl": QuantPerformanceProjection._float(item.get("net_realized_pnl")),
            "realized_r": efficiency["realized_r"],
            "entry_commission_usdt": entry_fee,
            "exit_commission_usdt": exit_fee,
            "total_commission_usdt": total_fee,
            "slippage_cost_usdt": QuantPerformanceProjection._slippage_cost_usdt(item),
            "mfe_capture_ratio": efficiency["mfe_capture_ratio"],
            "profit_giveback_r": efficiency["profit_giveback_r"],
            "mae_utilization_r": efficiency["mae_utilization_r"],
            "trade_diagnostic": efficiency["diagnostic"],
        }

    @classmethod
    def _historical_failures(cls, item: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        if str(item.get("status", "")).upper() != "CLOSED":
            failures.append("NOT_CLOSED")
        for field in (
            "entry_fill_price",
            "exit_fill_price",
            "quantity",
            "initial_stop_loss",
            "initial_risk_price_distance",
            "initial_risk_usdt",
            "trade_path_highest_price",
            "trade_path_lowest_price",
            "holding_seconds",
        ):
            if QuantPerformanceProjection._float(item.get(field)) is None:
                failures.append(f"MISSING_{field.upper()}")
        if not item.get("entry_market_regime"):
            failures.append("MISSING_ENTRY_MARKET_REGIME")
        return failures

    @classmethod
    def _historical_row(cls, item: dict[str, Any]) -> dict[str, Any]:
        quantity = QuantPerformanceProjection._float(item.get("quantity"))
        entry_price = QuantPerformanceProjection._float(item.get("entry_price"))
        entry_fill = QuantPerformanceProjection._float(item.get("entry_fill_price"))
        exit_price = QuantPerformanceProjection._float(item.get("exit_price"))
        exit_fill = QuantPerformanceProjection._float(item.get("exit_fill_price"))
        slippage = None
        if None not in (quantity, entry_price, entry_fill, exit_price, exit_fill):
            assert quantity is not None
            assert entry_price is not None
            assert entry_fill is not None
            assert exit_price is not None
            assert exit_fill is not None
            slippage = quantity * (abs(entry_fill - entry_price) + abs(exit_fill - exit_price))

        return {
            "order_id": str(item.get("order_id", "")),
            "strategy_id": str(item.get("strategy_id", "baseline")).lower(),
            "symbol": str(item.get("symbol", "")).upper(),
            "side": str(item.get("side", "")).lower(),
            "opened_at": item.get("created_at"),
            "closed_at": item.get("closed_at"),
            "exit_reason": item.get("exit_reason"),
            "data_origin": "historical_replay",
            "entry_price": entry_price,
            "entry_fill_price": entry_fill,
            "quantity": quantity,
            "initial_stop_loss": QuantPerformanceProjection._float(item.get("initial_stop_loss")),
            "initial_risk_price_distance": QuantPerformanceProjection._float(
                item.get("initial_risk_price_distance")
            ),
            "initial_risk_usdt": QuantPerformanceProjection._float(item.get("initial_risk_usdt")),
            "entry_market_regime": item.get("entry_market_regime"),
            "exit_price": exit_price,
            "exit_fill_price": exit_fill,
            "holding_seconds": QuantPerformanceProjection._float(item.get("holding_seconds")),
            "trade_path_highest_price": QuantPerformanceProjection._float(
                item.get("trade_path_highest_price")
            ),
            "trade_path_lowest_price": QuantPerformanceProjection._float(
                item.get("trade_path_lowest_price")
            ),
            "trade_path_observation_count": int(item.get("trade_path_observation_count") or 0),
            "mae_usdt": QuantPerformanceProjection._float(item.get("mae_usdt")),
            "mfe_usdt": QuantPerformanceProjection._float(item.get("mfe_usdt")),
            "mae_r": QuantPerformanceProjection._float(item.get("mae_r")),
            "mfe_r": QuantPerformanceProjection._float(item.get("mfe_r")),
            "gross_realized_pnl": QuantPerformanceProjection._float(item.get("gross_realized_pnl")),
            "net_realized_pnl": QuantPerformanceProjection._float(item.get("net_realized_pnl")),
            "realized_r": QuantPerformanceProjection._float(item.get("realized_r")),
            "entry_commission_usdt": QuantPerformanceProjection._float(
                item.get("entry_commission_usdt")
            ),
            "exit_commission_usdt": QuantPerformanceProjection._float(item.get("exit_commission_usdt")),
            "total_commission_usdt": QuantPerformanceProjection._float(
                item.get("total_commission_usdt")
            ),
            "slippage_cost_usdt": slippage,
            "mfe_capture_ratio": QuantPerformanceProjection._float(item.get("mfe_capture_ratio")),
            "profit_giveback_r": QuantPerformanceProjection._float(item.get("profit_giveback_r")),
            "mae_utilization_r": QuantPerformanceProjection._float(item.get("mae_utilization_r")),
            "trade_diagnostic": item.get("trade_diagnostic"),
        }

    @classmethod
    def build(
        cls,
        positions: list[dict[str, Any]],
        *,
        historical_trades: list[dict[str, Any]] | None = None,
        source: ResearchSource = "production",
        strategy_id: str | None = None,
        regime: str | None = None,
    ) -> dict[str, Any]:
        normalized_strategy = strategy_id.strip().lower() if strategy_id else None
        normalized_regime = regime.strip().upper() if regime else None
        historical = historical_trades or []

        production_candidates = (
            [
                item
                for item in positions
                if cls._matches_filters(
                    item,
                    strategy_id=normalized_strategy,
                    regime=normalized_regime,
                )
            ]
            if source in {"production", "combined"}
            else []
        )
        historical_candidates = (
            [
                item
                for item in historical
                if cls._matches_filters(
                    item,
                    strategy_id=normalized_strategy,
                    regime=normalized_regime,
                )
            ]
            if source in {"historical", "combined"}
            else []
        )

        rows: list[dict[str, Any]] = []
        exclusions: Counter[str] = Counter()
        for item in production_candidates:
            failures = ProductionAnalyticsReadinessProjection.qualification_failures(item)
            if not failures:
                failures = cls._row_validation_failures(item)
            if failures:
                exclusions.update(failures)
                continue
            rows.append(cls._production_row(item))

        for item in historical_candidates:
            failures = cls._historical_failures(item)
            if failures:
                exclusions.update(failures)
                continue
            rows.append(cls._historical_row(item))

        rows.sort(
            key=lambda row: (
                str(row.get("closed_at") or ""),
                str(row.get("order_id") or ""),
            )
        )
        strategies = sorted({str(row["strategy_id"]) for row in rows})
        regimes = sorted({str(row["entry_market_regime"]) for row in rows})
        origins = sorted({str(row["data_origin"]) for row in rows})

        total_candidates = len(production_candidates) + len(historical_candidates)
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "generated_at": cls._now(),
            "basis": cls.BASIS,
            "read_only": True,
            "filters": {
                "source": source,
                "strategy_id": normalized_strategy,
                "entry_market_regime": normalized_regime,
            },
            "columns": {
                "metadata": list(cls.METADATA_COLUMNS),
                "features": list(cls.FEATURE_COLUMNS),
                "targets": list(cls.TARGET_COLUMNS),
                "all": list(cls.COLUMNS),
            },
            "metadata": {
                "source_positions": len(positions),
                "source_historical_trades": len(historical),
                "filtered_candidates": total_candidates,
                "qualified_trades": len(rows),
                "excluded_candidates": total_candidates - len(rows),
                "exclusion_reason_counts": dict(sorted(exclusions.items())),
                "strategies": strategies,
                "market_regimes": regimes,
                "data_origins": origins,
            },
            "rows": rows,
        }
