from __future__ import annotations

import math
from collections import Counter
from typing import Any

from app.research.trade_dataset import ResearchSource, ResearchTradeDatasetProjection


class ResearchFeatureDatasetProjection:
    """Build leakage-controlled model features from canonical research trade rows."""

    SCHEMA_VERSION = "research_feature_schema_v2"
    SOURCE_SCHEMA_VERSION = ResearchTradeDatasetProjection.SCHEMA_VERSION
    MIN_TRAINING_SAMPLES = 30
    MIN_FEATURE_COVERAGE_PCT = 95.0

    CATEGORICAL_FEATURES = (
        "strategy_id",
        "side",
        "entry_market_regime",
    )
    NUMERIC_FEATURES = (
        "entry_price",
        "entry_fill_price",
        "quantity",
        "initial_stop_loss",
        "initial_risk_price_distance",
        "initial_risk_usdt",
        "entry_stop_distance_pct",
        "initial_risk_pct_of_notional",
        "side_direction",
    )
    MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
    TARGETS = (
        "net_realized_pnl",
        "realized_r",
        "mae_r",
        "mfe_r",
        "mfe_capture_ratio",
        "profit_giveback_r",
        "trade_diagnostic",
    )
    FORBIDDEN_MODEL_FEATURES = frozenset(
        set(ResearchTradeDatasetProjection.TARGET_COLUMNS)
        | {
            "closed_at",
            "exit_reason",
            "trade_path_highest_price",
            "trade_path_lowest_price",
            "trade_path_observation_count",
            "data_origin",
        }
    )

    @classmethod
    def validate_feature_names(cls, feature_names: list[str] | tuple[str, ...]) -> dict[str, Any]:
        normalized = [str(name) for name in feature_names]
        forbidden = sorted(set(normalized) & cls.FORBIDDEN_MODEL_FEATURES)
        unknown = sorted(set(normalized) - set(cls.MODEL_FEATURES))
        return {
            "status": "PASS" if not forbidden and not unknown else "FAIL",
            "forbidden_features": forbidden,
            "unknown_features": unknown,
        }

    @staticmethod
    def _float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @classmethod
    def _feature_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        entry_price = cls._float(row.get("entry_price"))
        entry_fill_price = cls._float(row.get("entry_fill_price"))
        quantity = cls._float(row.get("quantity"))
        initial_stop = cls._float(row.get("initial_stop_loss"))
        initial_risk = cls._float(row.get("initial_risk_usdt"))

        stop_distance_pct = None
        if entry_price is not None and entry_price > 0 and initial_stop is not None:
            stop_distance_pct = abs(initial_stop - entry_price) / entry_price * 100

        risk_pct_of_notional = None
        if (
            initial_risk is not None
            and entry_fill_price is not None
            and entry_fill_price > 0
            and quantity is not None
            and quantity > 0
        ):
            notional = entry_fill_price * quantity
            if notional > 0:
                risk_pct_of_notional = initial_risk / notional * 100

        side = str(row.get("side", "")).lower()
        side_direction = 1.0 if side == "buy" else -1.0 if side == "sell" else None

        features = {
            "strategy_id": row.get("strategy_id"),
            "side": side,
            "entry_market_regime": row.get("entry_market_regime"),
            "entry_price": entry_price,
            "entry_fill_price": entry_fill_price,
            "quantity": quantity,
            "initial_stop_loss": initial_stop,
            "initial_risk_price_distance": cls._float(row.get("initial_risk_price_distance")),
            "initial_risk_usdt": initial_risk,
            "entry_stop_distance_pct": stop_distance_pct,
            "initial_risk_pct_of_notional": risk_pct_of_notional,
            "side_direction": side_direction,
        }
        targets = {name: row.get(name) for name in cls.TARGETS}
        return {
            "order_id": row.get("order_id"),
            "data_origin": row.get("data_origin"),
            "feature_available_at": row.get("opened_at"),
            "features": features,
            "targets": targets,
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
        trade_dataset = ResearchTradeDatasetProjection.build(
            positions,
            historical_trades=historical_trades,
            source=source,
            strategy_id=strategy_id,
            regime=regime,
        )
        rows = [cls._feature_row(row) for row in trade_dataset["rows"]]
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "source_schema_version": cls.SOURCE_SCHEMA_VERSION,
            "basis": "canonical_research_trade_rows",
            "read_only": True,
            "filters": trade_dataset["filters"],
            "feature_contract": {
                "categorical": list(cls.CATEGORICAL_FEATURES),
                "numeric": list(cls.NUMERIC_FEATURES),
                "model_features": list(cls.MODEL_FEATURES),
                "targets": list(cls.TARGETS),
                "feature_timestamp_rule": "feature_available_at_must_not_be_after_decision_time",
            },
            "rows": rows,
        }

    @classmethod
    def quality(
        cls,
        positions: list[dict[str, Any]],
        *,
        historical_trades: list[dict[str, Any]] | None = None,
        source: ResearchSource = "production",
        strategy_id: str | None = None,
        regime: str | None = None,
    ) -> dict[str, Any]:
        dataset = cls.build(
            positions,
            historical_trades=historical_trades,
            source=source,
            strategy_id=strategy_id,
            regime=regime,
        )
        rows = dataset["rows"]
        sample_size = len(rows)
        leakage = cls.validate_feature_names(list(cls.MODEL_FEATURES))

        order_ids = [str(row.get("order_id")) for row in rows]
        duplicate_count = sum(count - 1 for count in Counter(order_ids).values() if count > 1)

        total_cells = sample_size * len(cls.MODEL_FEATURES)
        populated_cells = 0
        invalid_rows = 0
        for row in rows:
            features = row["features"]
            row_invalid = False
            for name in cls.MODEL_FEATURES:
                value = features.get(name)
                if value is not None and value != "":
                    populated_cells += 1
                if name in cls.NUMERIC_FEATURES and value is not None:
                    if cls._float(value) is None:
                        row_invalid = True
            if row_invalid:
                invalid_rows += 1

        coverage = round(populated_cells / total_cells * 100, 4) if total_cells else 0.0
        data_ready = (
            sample_size > 0
            and coverage >= cls.MIN_FEATURE_COVERAGE_PCT
            and duplicate_count == 0
            and invalid_rows == 0
            and leakage["status"] == "PASS"
        )
        training_ready = data_ready and sample_size >= cls.MIN_TRAINING_SAMPLES

        return {
            "schema_version": cls.SCHEMA_VERSION,
            "source_schema_version": cls.SOURCE_SCHEMA_VERSION,
            "filters": dataset["filters"],
            "sample_size": sample_size,
            "quality": {
                "feature_coverage_pct": coverage,
                "duplicate_order_ids": duplicate_count,
                "invalid_rows": invalid_rows,
                "leakage_check": leakage,
            },
            "thresholds": {
                "minimum_feature_coverage_pct": cls.MIN_FEATURE_COVERAGE_PCT,
                "minimum_training_samples": cls.MIN_TRAINING_SAMPLES,
            },
            "readiness": {
                "pipeline": "READY",
                "dataset": "READY" if data_ready else "NOT_READY",
                "training": "READY" if training_ready else "NOT_READY",
            },
        }

    @classmethod
    def temporal_split(
        cls,
        positions: list[dict[str, Any]],
        *,
        historical_trades: list[dict[str, Any]] | None = None,
        source: ResearchSource = "production",
        strategy_id: str | None = None,
        regime: str | None = None,
    ) -> dict[str, Any]:
        dataset = cls.build(
            positions,
            historical_trades=historical_trades,
            source=source,
            strategy_id=strategy_id,
            regime=regime,
        )
        rows = sorted(
            dataset["rows"],
            key=lambda row: (
                str(row.get("feature_available_at") or ""),
                str(row.get("order_id") or ""),
            ),
        )
        total = len(rows)
        train_end = int(total * 0.70)
        validation_end = train_end + int(total * 0.15)
        train = rows[:train_end]
        validation = rows[train_end:validation_end]
        test = rows[validation_end:]

        def ids(items: list[dict[str, Any]]) -> list[str]:
            return [str(item.get("order_id")) for item in items]

        def bounds(items: list[dict[str, Any]]) -> dict[str, str | None]:
            if not items:
                return {"first": None, "last": None}
            return {
                "first": str(items[0].get("feature_available_at") or ""),
                "last": str(items[-1].get("feature_available_at") or ""),
            }

        train_ids = set(ids(train))
        validation_ids = set(ids(validation))
        test_ids = set(ids(test))
        no_overlap = not (
            train_ids & validation_ids or train_ids & test_ids or validation_ids & test_ids
        )
        chronological = True
        if train and validation:
            chronological = chronological and str(train[-1].get("feature_available_at") or "") <= str(
                validation[0].get("feature_available_at") or ""
            )
        if validation and test:
            chronological = chronological and str(validation[-1].get("feature_available_at") or "") <= str(
                test[0].get("feature_available_at") or ""
            )

        split_ready = total >= cls.MIN_TRAINING_SAMPLES and no_overlap and chronological
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "filters": dataset["filters"],
            "method": "chronological_holdout",
            "random_shuffle": False,
            "ratios": {"train": 0.70, "validation": 0.15, "test": 0.15},
            "sample_size": total,
            "counts": {
                "train": len(train),
                "validation": len(validation),
                "test": len(test),
            },
            "time_bounds": {
                "train": bounds(train),
                "validation": bounds(validation),
                "test": bounds(test),
            },
            "checks": {
                "order_id_overlap": "PASS" if no_overlap else "FAIL",
                "chronological_order": "PASS" if chronological else "FAIL",
            },
            "order_ids": {
                "train": ids(train),
                "validation": ids(validation),
                "test": ids(test),
            },
            "readiness": "READY" if split_ready else "NOT_READY",
        }
