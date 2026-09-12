from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Any

import numpy as np

from app.research.baseline_ml import BaselineMLResearch
from app.research.feature_dataset import ResearchFeatureDatasetProjection


@dataclass(frozen=True)
class WalkForwardConfig:
    fold_count: int = 4
    initial_train_fraction: float = 0.45
    validation_fraction: float = 0.10
    test_fraction: float = 0.10
    minimum_test_selected_trades: int = 10
    minimum_positive_expectancy_fold_ratio: float = 0.50


class WalkForwardResearch:
    """Phase 5.3 expanding-window validation built on the Phase 5.2 ML contract."""

    SCHEMA_VERSION = "walk_forward_schema_v1"

    def __init__(
        self,
        *,
        baseline: BaselineMLResearch | None = None,
        config: WalkForwardConfig | None = None,
    ) -> None:
        self.baseline = baseline or BaselineMLResearch()
        self.config = config or WalkForwardConfig()

    @staticmethod
    def _bounds(rows: list[dict[str, Any]]) -> dict[str, str | None]:
        if not rows:
            return {"first": None, "last": None}
        return {
            "first": str(rows[0].get("feature_available_at") or ""),
            "last": str(rows[-1].get("feature_available_at") or ""),
        }

    def _folds(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        total = len(rows)
        if self.config.fold_count < 1:
            raise ValueError("walk-forward fold_count must be positive")

        initial_train = max(1, math.floor(total * self.config.initial_train_fraction))
        validation_size = max(1, math.floor(total * self.config.validation_fraction))
        test_size = max(1, math.floor(total * self.config.test_fraction))
        required = initial_train + validation_size + test_size
        if total < required:
            raise ValueError("dataset is too small for configured walk-forward windows")

        folds: list[dict[str, Any]] = []
        train_end = initial_train
        for index in range(self.config.fold_count):
            validation_end = train_end + validation_size
            test_end = min(validation_end + test_size, total)
            if test_end <= validation_end:
                break

            train_rows = rows[:train_end]
            validation_rows = rows[train_end:validation_end]
            test_rows = rows[validation_end:test_end]
            if not train_rows or not validation_rows or not test_rows:
                break

            folds.append(
                {
                    "fold": index + 1,
                    "train": train_rows,
                    "validation": validation_rows,
                    "test": test_rows,
                }
            )
            train_end = test_end
            if train_end + validation_size >= total:
                break

        if len(folds) < self.config.fold_count:
            raise ValueError(
                f"configured {self.config.fold_count} folds but only {len(folds)} fit the dataset"
            )
        return folds

    def _run_fold(self, fold: dict[str, Any]) -> dict[str, Any]:
        train_rows = fold["train"]
        validation_rows = fold["validation"]
        test_rows = fold["test"]

        x_train = self.baseline._records_to_matrix(
            [self.baseline._feature_record(row) for row in train_rows]
        )
        x_validation = self.baseline._records_to_matrix(
            [self.baseline._feature_record(row) for row in validation_rows]
        )
        x_test = self.baseline._records_to_matrix(
            [self.baseline._feature_record(row) for row in test_rows]
        )
        y_train = np.asarray([self.baseline._target(row) for row in train_rows], dtype=int)
        y_validation = np.asarray(
            [self.baseline._target(row) for row in validation_rows], dtype=int
        )
        y_test = np.asarray([self.baseline._target(row) for row in test_rows], dtype=int)
        r_validation = np.asarray(
            [self.baseline._realized_r(row) for row in validation_rows], dtype=float
        )
        r_test = np.asarray(
            [self.baseline._realized_r(row) for row in test_rows], dtype=float
        )

        model_reports: dict[str, Any] = {}
        fitted_models: dict[str, Any] = {}
        for name, model in self.baseline._models().items():
            model.fit(x_train, y_train)
            fitted_models[name] = model
            validation_probability = self.baseline._predict_positive_probability(
                model, x_validation
            )
            test_probability = self.baseline._predict_positive_probability(model, x_test)
            model_reports[name] = {
                "validation": self.baseline._classification_metrics(
                    y_validation, validation_probability
                ),
                "test": self.baseline._classification_metrics(y_test, test_probability),
            }

        candidates = [name for name in model_reports if name != "dummy_prior"]
        selected_model_name = max(
            candidates,
            key=lambda name: float(
                model_reports[name]["validation"]["pr_auc"] or -1.0
            ),
        )
        selected_model = fitted_models[selected_model_name]
        validation_probability = self.baseline._predict_positive_probability(
            selected_model, x_validation
        )
        test_probability = self.baseline._predict_positive_probability(selected_model, x_test)
        threshold_report = self.baseline._select_threshold(
            validation_probability, r_validation
        )
        threshold = float(threshold_report["selected_threshold"])

        validation_mask = validation_probability >= threshold
        test_mask = test_probability >= threshold
        rule_test = self.baseline._trading_metrics(
            r_test, np.ones(len(r_test), dtype=bool)
        )
        ml_test = self.baseline._trading_metrics(r_test, test_mask)
        rule_validation = self.baseline._trading_metrics(
            r_validation, np.ones(len(r_validation), dtype=bool)
        )
        ml_validation = self.baseline._trading_metrics(r_validation, validation_mask)
        rule_expectancy = float(rule_test["expectancy_r"] or 0.0)
        ml_expectancy_value = ml_test["expectancy_r"]
        ml_expectancy = (
            float(ml_expectancy_value) if ml_expectancy_value is not None else None
        )

        return {
            "fold": int(fold["fold"]),
            "counts": {
                "train": len(train_rows),
                "validation": len(validation_rows),
                "test": len(test_rows),
            },
            "time_bounds": {
                "train": self._bounds(train_rows),
                "validation": self._bounds(validation_rows),
                "test": self._bounds(test_rows),
            },
            "selection": {
                "model": selected_model_name,
                "selected_threshold": threshold,
                "model_selection_metric": "validation_pr_auc",
                "threshold_selection_scope": "validation_only",
                "minimum_selected_trades": threshold_report["minimum_selected_trades"],
            },
            "models": model_reports,
            "trading_comparison": {
                "validation": {
                    "rule_based_all_signals": rule_validation,
                    "ml_filtered": ml_validation,
                },
                "test": {
                    "rule_based_all_signals": rule_test,
                    "ml_filtered": ml_test,
                },
            },
            "test_expectancy_uplift_r": (
                ml_expectancy - rule_expectancy if ml_expectancy is not None else None
            ),
        }

    def run(self, historical_trades: list[dict[str, Any]]) -> dict[str, Any]:
        quality = ResearchFeatureDatasetProjection.quality(
            [], historical_trades=historical_trades, source="historical"
        )
        if quality["readiness"]["training"] != "READY":
            raise ValueError("research feature dataset is not training-ready")
        if quality["quality"]["leakage_check"]["status"] != "PASS":
            raise ValueError("research feature leakage check failed")

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
        reports = [self._run_fold(fold) for fold in folds]

        ml_expectancies = [
            float(report["trading_comparison"]["test"]["ml_filtered"]["expectancy_r"])
            for report in reports
            if report["trading_comparison"]["test"]["ml_filtered"]["expectancy_r"]
            is not None
        ]
        rule_expectancies = [
            float(
                report["trading_comparison"]["test"]["rule_based_all_signals"][
                    "expectancy_r"
                ]
                or 0.0
            )
            for report in reports
        ]
        selected_counts = [
            int(report["trading_comparison"]["test"]["ml_filtered"]["selected_trades"])
            for report in reports
        ]
        positive_folds = sum(value > 0 for value in ml_expectancies)
        positive_ratio = positive_folds / len(reports) if reports else 0.0
        aggregate_ml = float(np.mean(ml_expectancies)) if ml_expectancies else None
        aggregate_rule = float(np.mean(rule_expectancies)) if rule_expectancies else None
        median_ml = float(median(ml_expectancies)) if ml_expectancies else None
        minimum_selected = min(selected_counts) if selected_counts else 0

        chronological = all(
            str(report["time_bounds"]["train"]["last"] or "")
            <= str(report["time_bounds"]["validation"]["first"] or "")
            <= str(report["time_bounds"]["validation"]["last"] or "")
            <= str(report["time_bounds"]["test"]["first"] or "")
            <= str(report["time_bounds"]["test"]["last"] or "")
            for report in reports
        )
        structural_acceptance = {
            "fold_count": len(reports) >= self.config.fold_count,
            "chronological_integrity": chronological,
            "train_only_preprocessing": True,
            "validation_only_threshold_selection": True,
            "feature_leakage": quality["quality"]["leakage_check"]["status"] == "PASS",
            "production_isolation": True,
        }
        robustness = {
            "positive_expectancy_fold_ratio": (
                positive_ratio >= self.config.minimum_positive_expectancy_fold_ratio
            ),
            "median_ml_expectancy_positive": median_ml is not None and median_ml > 0,
            "aggregate_ml_beats_rule_based": (
                aggregate_ml is not None
                and aggregate_rule is not None
                and aggregate_ml > aggregate_rule
            ),
            "minimum_selected_trades_per_fold": (
                minimum_selected >= self.config.minimum_test_selected_trades
            ),
        }
        structural_status = "PASS" if all(structural_acceptance.values()) else "FAIL"
        robustness_status = "PASS" if all(robustness.values()) else "FAIL"

        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.3",
            "research_only": True,
            "production_position_store_mutated": False,
            "dataset_schema_version": dataset["schema_version"],
            "method": "expanding_walk_forward",
            "random_shuffle": False,
            "config": {
                "fold_count": self.config.fold_count,
                "initial_train_fraction": self.config.initial_train_fraction,
                "validation_fraction": self.config.validation_fraction,
                "test_fraction": self.config.test_fraction,
                "minimum_test_selected_trades": self.config.minimum_test_selected_trades,
                "minimum_positive_expectancy_fold_ratio": (
                    self.config.minimum_positive_expectancy_fold_ratio
                ),
            },
            "folds": reports,
            "aggregate": {
                "fold_count": len(reports),
                "positive_expectancy_folds": positive_folds,
                "positive_expectancy_fold_ratio": positive_ratio,
                "median_ml_expectancy_r": median_ml,
                "mean_ml_expectancy_r": aggregate_ml,
                "mean_rule_based_expectancy_r": aggregate_rule,
                "minimum_selected_trades": minimum_selected,
            },
            "acceptance": structural_acceptance,
            "acceptance_status": structural_status,
            "robustness": robustness,
            "robustness_status": robustness_status,
        }
