from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any

import numpy as np

from app.research.baseline_ml import BaselineMLResearch
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.walk_forward import WalkForwardConfig, WalkForwardResearch


@dataclass(frozen=True)
class BenchmarkConfig:
    minimum_positive_expectancy_fold_ratio: float = 0.75
    maximum_single_fold_positive_r_contribution: float = 0.50
    maximum_single_regime_positive_r_contribution: float = 0.60
    minimum_profit_factor: float = 1.0
    minimum_segment_selected_trades: int = 5
    require_drawdown_improvement: bool = True


class ModelRuleBenchmark(WalkForwardResearch):
    """Phase 5.4 diagnostic benchmark for rule-based versus ML-filtered signals."""

    SCHEMA_VERSION = "model_rule_benchmark_schema_v1"

    def __init__(
        self,
        *,
        baseline: BaselineMLResearch | None = None,
        walk_forward_config: WalkForwardConfig | None = None,
        benchmark_config: BenchmarkConfig | None = None,
    ) -> None:
        super().__init__(baseline=baseline, config=walk_forward_config)
        self.benchmark_config = benchmark_config or BenchmarkConfig()

    @staticmethod
    def _year(value: Any) -> str:
        text = str(value or "")
        return text[:4] if len(text) >= 4 else "UNKNOWN"

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @classmethod
    def _metrics(
        cls,
        observations: list[dict[str, Any]],
        *,
        ml_filtered: bool,
    ) -> dict[str, float | int | None]:
        available = len(observations)
        selected = [
            row
            for row in observations
            if not ml_filtered or bool(row.get("ml_selected"))
        ]
        realized = [
            value
            for row in selected
            if (value := cls._safe_float(row.get("realized_r"))) is not None
        ]
        if not realized:
            return {
                "available_signals": available,
                "trade_count": 0,
                "selection_rate_pct": 0.0,
                "win_rate_pct": None,
                "expectancy_r": None,
                "total_realized_r": 0.0,
                "profit_factor": None,
                "max_drawdown_r": 0.0,
                "average_win_r": None,
                "average_loss_r": None,
            }

        gains = [value for value in realized if value > 0]
        losses = [value for value in realized if value < 0]
        gross_profit = float(sum(gains))
        gross_loss = float(abs(sum(losses)))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for value in realized:
            equity += value
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

        return {
            "available_signals": available,
            "trade_count": len(realized),
            "selection_rate_pct": float(len(realized) / available * 100) if available else 0.0,
            "win_rate_pct": float(sum(value > 0 for value in realized) / len(realized) * 100),
            "expectancy_r": float(np.mean(realized)),
            "total_realized_r": float(sum(realized)),
            "profit_factor": float(profit_factor) if profit_factor is not None else None,
            "max_drawdown_r": float(max_drawdown),
            "average_win_r": float(np.mean(gains)) if gains else None,
            "average_loss_r": float(np.mean(losses)) if losses else None,
        }

    @classmethod
    def _comparison(cls, observations: list[dict[str, Any]]) -> dict[str, Any]:
        rule = cls._metrics(observations, ml_filtered=False)
        ml = cls._metrics(observations, ml_filtered=True)
        rule_expectancy = cls._safe_float(rule.get("expectancy_r"))
        ml_expectancy = cls._safe_float(ml.get("expectancy_r"))
        uplift = (
            ml_expectancy - rule_expectancy
            if ml_expectancy is not None and rule_expectancy is not None
            else None
        )
        return {
            "rule_based": rule,
            "ml_filtered": ml,
            "expectancy_uplift_r": uplift,
        }

    @classmethod
    def _grouped(
        cls,
        observations: list[dict[str, Any]],
        key: str,
        *,
        minimum_selected_trades: int,
    ) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            groups[str(row.get(key) or "UNKNOWN")].append(row)

        result: list[dict[str, Any]] = []
        for value in sorted(groups):
            comparison = cls._comparison(groups[value])
            ml_count = int(comparison["ml_filtered"]["trade_count"])
            result.append(
                {
                    "segment": value,
                    "sample_sufficient": ml_count >= minimum_selected_trades,
                    **comparison,
                }
            )
        return result

    @staticmethod
    def _positive_r_concentration(rows: list[dict[str, Any]]) -> float:
        positive = [
            max(0.0, float(row["ml_filtered"]["total_realized_r"]))
            for row in rows
        ]
        total = sum(positive)
        if total <= 0:
            return 0.0
        return max(positive) / total

    def _observations_for_fold(
        self,
        fold: dict[str, Any],
        phase53_fold: dict[str, Any],
    ) -> list[dict[str, Any]]:
        train_rows = fold["train"]
        test_rows = fold["test"]
        model_name = str(phase53_fold["selection"]["model"])
        threshold = float(phase53_fold["selection"]["selected_threshold"])

        models = self.baseline._models()
        if model_name not in models:
            raise ValueError(f"Phase 5.3 selected unknown model: {model_name}")
        model = models[model_name]
        x_train = self.baseline._records_to_matrix(
            [self.baseline._feature_record(row) for row in train_rows]
        )
        y_train = np.asarray([self.baseline._target(row) for row in train_rows], dtype=int)
        x_test = self.baseline._records_to_matrix(
            [self.baseline._feature_record(row) for row in test_rows]
        )
        model.fit(x_train, y_train)
        probabilities = self.baseline._predict_positive_probability(model, x_test)

        observations: list[dict[str, Any]] = []
        for row, probability in zip(test_rows, probabilities, strict=True):
            features = row.get("features")
            feature_map = features if isinstance(features, dict) else {}
            timestamp = row.get("feature_available_at")
            observations.append(
                {
                    "fold": int(fold["fold"]),
                    "order_id": str(row.get("order_id") or ""),
                    "feature_available_at": timestamp,
                    "year": self._year(timestamp),
                    "strategy_id": str(feature_map.get("strategy_id") or "UNKNOWN"),
                    "side": str(feature_map.get("side") or "UNKNOWN").lower(),
                    "entry_market_regime": str(
                        feature_map.get("entry_market_regime") or "UNKNOWN"
                    ),
                    "realized_r": float(self.baseline._realized_r(row)),
                    "ml_probability": float(probability),
                    "ml_selected": bool(probability >= threshold),
                    "selected_threshold": threshold,
                    "selected_model": model_name,
                }
            )
        return observations

    def run(self, historical_trades: list[dict[str, Any]]) -> dict[str, Any]:
        phase53 = super().run(historical_trades)
        if phase53["acceptance_status"] != "PASS":
            raise ValueError("Phase 5.4 requires Phase 5.3 structural acceptance to pass")

        dataset = ResearchFeatureDatasetProjection.build(
            [], historical_trades=historical_trades, source="historical"
        )
        rows = sorted(
            dataset["rows"],
            key=lambda row: (
                str(row.get("feature_available_at") or ""),
                str(row.get("order_id") or ""),
            ),
        )
        folds = self._folds(rows)
        if len(folds) != len(phase53["folds"]):
            raise ValueError("Phase 5.3 fold count changed during Phase 5.4 benchmark")

        observations: list[dict[str, Any]] = []
        fold_rows: list[dict[str, Any]] = []
        for fold, phase53_fold in zip(folds, phase53["folds"], strict=True):
            current = self._observations_for_fold(fold, phase53_fold)
            observations.extend(current)
            fold_rows.append(
                {
                    "segment": str(fold["fold"]),
                    "sample_sufficient": True,
                    **self._comparison(current),
                }
            )

        minimum = self.benchmark_config.minimum_segment_selected_trades
        by_strategy = self._grouped(
            observations, "strategy_id", minimum_selected_trades=minimum
        )
        by_side = self._grouped(observations, "side", minimum_selected_trades=minimum)
        by_regime = self._grouped(
            observations, "entry_market_regime", minimum_selected_trades=minimum
        )
        by_year = self._grouped(observations, "year", minimum_selected_trades=minimum)
        aggregate = self._comparison(observations)

        fold_expectancies = [
            float(row["ml_filtered"]["expectancy_r"])
            for row in fold_rows
            if row["ml_filtered"]["expectancy_r"] is not None
        ]
        positive_folds = sum(value > 0 for value in fold_expectancies)
        positive_ratio = positive_folds / len(fold_rows) if fold_rows else 0.0
        fold_concentration = self._positive_r_concentration(fold_rows)
        regime_concentration = self._positive_r_concentration(by_regime)
        ml_metrics = aggregate["ml_filtered"]
        rule_metrics = aggregate["rule_based"]
        ml_expectancy = self._safe_float(ml_metrics.get("expectancy_r"))
        profit_factor = self._safe_float(ml_metrics.get("profit_factor"))
        ml_drawdown = float(ml_metrics["max_drawdown_r"])
        rule_drawdown = float(rule_metrics["max_drawdown_r"])

        stability = {
            "fold_count": len(fold_rows),
            "positive_expectancy_folds": positive_folds,
            "positive_expectancy_fold_ratio": positive_ratio,
            "mean_ml_expectancy_r": (
                float(np.mean(fold_expectancies)) if fold_expectancies else None
            ),
            "median_ml_expectancy_r": (
                float(median(fold_expectancies)) if fold_expectancies else None
            ),
            "worst_fold_expectancy_r": min(fold_expectancies) if fold_expectancies else None,
            "expectancy_stddev_r": (
                float(np.std(fold_expectancies)) if fold_expectancies else None
            ),
            "maximum_single_fold_positive_r_contribution": fold_concentration,
            "maximum_single_regime_positive_r_contribution": regime_concentration,
        }

        benchmark_acceptance = {
            "aggregate_ml_expectancy_positive": (
                ml_expectancy is not None and ml_expectancy > 0
            ),
            "positive_expectancy_fold_ratio": (
                positive_ratio
                >= self.benchmark_config.minimum_positive_expectancy_fold_ratio
            ),
            "profit_factor": (
                profit_factor is not None
                and profit_factor > self.benchmark_config.minimum_profit_factor
            ),
            "fold_edge_concentration": (
                fold_concentration
                <= self.benchmark_config.maximum_single_fold_positive_r_contribution
            ),
            "regime_edge_concentration": (
                regime_concentration
                <= self.benchmark_config.maximum_single_regime_positive_r_contribution
            ),
            "drawdown": (
                not self.benchmark_config.require_drawdown_improvement
                or ml_drawdown <= rule_drawdown
            ),
            "production_isolation": True,
            "feature_leakage": bool(phase53["acceptance"]["feature_leakage"]),
            "chronological_integrity": bool(
                phase53["acceptance"]["chronological_integrity"]
            ),
        }
        status = "PASS" if all(benchmark_acceptance.values()) else "FAIL"

        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.4",
            "research_only": True,
            "production_position_store_mutated": False,
            "method": "model_vs_rule_based_diagnostic_benchmark",
            "random_shuffle": False,
            "source_phase": {
                "phase": phase53["phase"],
                "schema_version": phase53["schema_version"],
                "acceptance_status": phase53["acceptance_status"],
                "robustness_status": phase53["robustness_status"],
            },
            "config": {
                "minimum_positive_expectancy_fold_ratio": (
                    self.benchmark_config.minimum_positive_expectancy_fold_ratio
                ),
                "maximum_single_fold_positive_r_contribution": (
                    self.benchmark_config.maximum_single_fold_positive_r_contribution
                ),
                "maximum_single_regime_positive_r_contribution": (
                    self.benchmark_config.maximum_single_regime_positive_r_contribution
                ),
                "minimum_profit_factor": self.benchmark_config.minimum_profit_factor,
                "minimum_segment_selected_trades": minimum,
                "require_drawdown_improvement": (
                    self.benchmark_config.require_drawdown_improvement
                ),
            },
            "aggregate": aggregate,
            "stability": stability,
            "segments": {
                "fold": fold_rows,
                "strategy": by_strategy,
                "side": by_side,
                "market_regime": by_regime,
                "year": by_year,
            },
            "acceptance": benchmark_acceptance,
            "acceptance_status": status,
        }
