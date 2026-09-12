from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.research.feature_dataset import ResearchFeatureDatasetProjection


@dataclass(frozen=True)
class BaselineMLConfig:
    target_name: str = "trade_profitable"
    minimum_validation_selection: int = 10
    threshold_start: float = 0.30
    threshold_stop: float = 0.80
    threshold_step: float = 0.05
    random_state: int = 42


class BaselineMLResearch:
    """Train leakage-controlled Phase 5.2 baseline classifiers on research data only."""

    SCHEMA_VERSION = "baseline_ml_schema_v1"

    def __init__(self, config: BaselineMLConfig | None = None) -> None:
        self.config = config or BaselineMLConfig()

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
    def _target(cls, row: dict[str, Any]) -> int:
        targets = row.get("targets")
        target_map = targets if isinstance(targets, dict) else {}
        realized_r = cls._safe_float(target_map.get("realized_r"))
        if realized_r is None:
            raise ValueError("baseline ML requires realized_r target for every research row")
        return 1 if realized_r > 0 else 0

    @classmethod
    def _realized_r(cls, row: dict[str, Any]) -> float:
        targets = row.get("targets")
        target_map = targets if isinstance(targets, dict) else {}
        realized_r = cls._safe_float(target_map.get("realized_r"))
        if realized_r is None:
            raise ValueError("baseline ML requires realized_r target for every research row")
        return realized_r

    @staticmethod
    def _feature_record(row: dict[str, Any]) -> dict[str, Any]:
        features = row.get("features")
        if not isinstance(features, dict):
            raise ValueError("research feature row is missing features")
        return {
            name: features.get(name)
            for name in ResearchFeatureDatasetProjection.MODEL_FEATURES
        }

    @staticmethod
    def _rows_by_ids(
        rows: list[dict[str, Any]],
        ids: list[str],
    ) -> list[dict[str, Any]]:
        lookup = {str(row.get("order_id")): row for row in rows}
        selected: list[dict[str, Any]] = []
        for order_id in ids:
            row = lookup.get(str(order_id))
            if row is None:
                raise ValueError(f"temporal split references unknown order_id: {order_id}")
            selected.append(row)
        return selected

    @staticmethod
    def _records_to_matrix(records: list[dict[str, Any]]) -> np.ndarray:
        categorical = set(ResearchFeatureDatasetProjection.CATEGORICAL_FEATURES)
        matrix: list[list[Any]] = []
        for record in records:
            values: list[Any] = []
            for name in ResearchFeatureDatasetProjection.MODEL_FEATURES:
                value = record.get(name)
                if name in categorical:
                    values.append(str(value) if value not in (None, "") else "__MISSING__")
                else:
                    values.append(np.nan if value is None else value)
            matrix.append(values)
        return np.asarray(matrix, dtype=object)

    @staticmethod
    def _preprocessor() -> ColumnTransformer:
        categorical_count = len(ResearchFeatureDatasetProjection.CATEGORICAL_FEATURES)
        categorical_indices = list(range(categorical_count))
        numeric_indices = list(
            range(
                categorical_count,
                len(ResearchFeatureDatasetProjection.MODEL_FEATURES),
            )
        )
        categorical_pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore")),
            ]
        )
        numeric_pipeline = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )
        return ColumnTransformer(
            transformers=[
                ("categorical", categorical_pipeline, categorical_indices),
                ("numeric", numeric_pipeline, numeric_indices),
            ]
        )

    def _models(self) -> dict[str, Pipeline]:
        return {
            "dummy_prior": Pipeline(
                steps=[
                    ("preprocess", self._preprocessor()),
                    ("model", DummyClassifier(strategy="prior")),
                ]
            ),
            "logistic_regression": Pipeline(
                steps=[
                    ("preprocess", self._preprocessor()),
                    (
                        "model",
                        LogisticRegression(
                            class_weight="balanced",
                            max_iter=2000,
                            random_state=self.config.random_state,
                        ),
                    ),
                ]
            ),
        }

    @staticmethod
    def _predict_positive_probability(
        model: Pipeline,
        x: np.ndarray,
    ) -> np.ndarray:
        probabilities = model.predict_proba(x)
        classes = list(model.classes_)
        if 1 not in classes:
            return np.zeros(len(x), dtype=float)
        return probabilities[:, classes.index(1)]

    @staticmethod
    def _classification_metrics(
        y_true: np.ndarray,
        probabilities: np.ndarray,
    ) -> dict[str, float | None]:
        predictions = (probabilities >= 0.5).astype(int)
        unique = np.unique(y_true)
        roc_auc = float(roc_auc_score(y_true, probabilities)) if len(unique) == 2 else None
        pr_auc = (
            float(average_precision_score(y_true, probabilities))
            if len(unique) == 2
            else None
        )
        return {
            "accuracy": float(accuracy_score(y_true, predictions)),
            "precision": float(precision_score(y_true, predictions, zero_division=0)),
            "recall": float(recall_score(y_true, predictions, zero_division=0)),
            "roc_auc": roc_auc,
            "pr_auc": pr_auc,
            "brier_score": float(brier_score_loss(y_true, probabilities)),
        }

    @staticmethod
    def _trading_metrics(
        realized_r: np.ndarray,
        mask: np.ndarray,
    ) -> dict[str, float | int | None]:
        selected = realized_r[mask]
        if len(selected) == 0:
            return {
                "selected_trades": 0,
                "selection_rate_pct": 0.0,
                "win_rate_pct": None,
                "expectancy_r": None,
                "total_realized_r": 0.0,
            }
        return {
            "selected_trades": int(len(selected)),
            "selection_rate_pct": float(len(selected) / len(realized_r) * 100),
            "win_rate_pct": float(np.mean(selected > 0) * 100),
            "expectancy_r": float(np.mean(selected)),
            "total_realized_r": float(np.sum(selected)),
        }

    def _select_threshold(
        self,
        probabilities: np.ndarray,
        realized_r: np.ndarray,
    ) -> dict[str, Any]:
        ten_percent = max(1, math.ceil(len(realized_r) * 0.10))
        minimum_selected = min(self.config.minimum_validation_selection, ten_percent)
        candidates: list[dict[str, Any]] = []
        threshold = self.config.threshold_start
        while threshold <= self.config.threshold_stop + 1e-9:
            mask = probabilities >= threshold
            metrics = self._trading_metrics(realized_r, mask)
            candidates.append({"threshold": round(threshold, 4), **metrics})
            threshold += self.config.threshold_step

        eligible = [
            candidate
            for candidate in candidates
            if int(candidate["selected_trades"]) >= minimum_selected
            and candidate["expectancy_r"] is not None
        ]
        if not eligible:
            raise ValueError("validation set has too few selected trades for threshold selection")
        best = max(
            eligible,
            key=lambda candidate: (
                float(candidate["expectancy_r"]),
                float(candidate["win_rate_pct"] or 0.0),
                int(candidate["selected_trades"]),
            ),
        )
        return {
            "selected_threshold": float(best["threshold"]),
            "minimum_selected_trades": minimum_selected,
            "selection_basis": "maximize_validation_expectancy_r_with_minimum_trade_count",
            "candidates": candidates,
        }

    def run(self, historical_trades: list[dict[str, Any]]) -> dict[str, Any]:
        quality = ResearchFeatureDatasetProjection.quality(
            [],
            historical_trades=historical_trades,
            source="historical",
        )
        if quality["readiness"]["training"] != "READY":
            raise ValueError("research feature dataset is not training-ready")
        if quality["quality"]["leakage_check"]["status"] != "PASS":
            raise ValueError("research feature leakage check failed")

        dataset = ResearchFeatureDatasetProjection.build(
            [],
            historical_trades=historical_trades,
            source="historical",
        )
        split = ResearchFeatureDatasetProjection.temporal_split(
            [],
            historical_trades=historical_trades,
            source="historical",
        )
        if split["readiness"] != "READY":
            raise ValueError("chronological research split is not ready")

        rows = dataset["rows"]
        train_rows = self._rows_by_ids(rows, split["order_ids"]["train"])
        validation_rows = self._rows_by_ids(rows, split["order_ids"]["validation"])
        test_rows = self._rows_by_ids(rows, split["order_ids"]["test"])

        x_train = self._records_to_matrix(
            [self._feature_record(row) for row in train_rows]
        )
        x_validation = self._records_to_matrix(
            [self._feature_record(row) for row in validation_rows]
        )
        x_test = self._records_to_matrix(
            [self._feature_record(row) for row in test_rows]
        )
        y_train = np.asarray([self._target(row) for row in train_rows], dtype=int)
        y_validation = np.asarray(
            [self._target(row) for row in validation_rows],
            dtype=int,
        )
        y_test = np.asarray([self._target(row) for row in test_rows], dtype=int)
        r_validation = np.asarray(
            [self._realized_r(row) for row in validation_rows],
            dtype=float,
        )
        r_test = np.asarray(
            [self._realized_r(row) for row in test_rows],
            dtype=float,
        )

        model_reports: dict[str, Any] = {}
        fitted_models: dict[str, Pipeline] = {}
        for name, model in self._models().items():
            model.fit(x_train, y_train)
            fitted_models[name] = model
            validation_probability = self._predict_positive_probability(
                model,
                x_validation,
            )
            test_probability = self._predict_positive_probability(model, x_test)
            model_reports[name] = {
                "validation": self._classification_metrics(
                    y_validation,
                    validation_probability,
                ),
                "test": self._classification_metrics(y_test, test_probability),
            }

        candidate_models = [name for name in model_reports if name != "dummy_prior"]
        selected_model_name = max(
            candidate_models,
            key=lambda name: float(
                model_reports[name]["validation"]["pr_auc"] or -1.0
            ),
        )
        selected_model = fitted_models[selected_model_name]
        validation_probability = self._predict_positive_probability(
            selected_model,
            x_validation,
        )
        test_probability = self._predict_positive_probability(selected_model, x_test)
        threshold_report = self._select_threshold(
            validation_probability,
            r_validation,
        )
        threshold = float(threshold_report["selected_threshold"])

        validation_mask = validation_probability >= threshold
        test_mask = test_probability >= threshold
        baseline_validation = self._trading_metrics(
            r_validation,
            np.ones(len(r_validation), dtype=bool),
        )
        baseline_test = self._trading_metrics(
            r_test,
            np.ones(len(r_test), dtype=bool),
        )
        filtered_validation = self._trading_metrics(r_validation, validation_mask)
        filtered_test = self._trading_metrics(r_test, test_mask)

        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.2",
            "research_only": True,
            "production_position_store_mutated": False,
            "dataset_schema_version": dataset["schema_version"],
            "target": {
                "name": self.config.target_name,
                "definition": "realized_r > 0",
                "positive_class": 1,
            },
            "feature_contract": dataset["feature_contract"],
            "split": {
                "method": split["method"],
                "random_shuffle": split["random_shuffle"],
                "counts": split["counts"],
                "time_bounds": split["time_bounds"],
                "checks": split["checks"],
            },
            "preprocessing": {
                "fit_scope": "train_only",
                "categorical": "most_frequent_imputer_plus_one_hot",
                "numeric": "median_imputer_plus_standard_scaler",
            },
            "models": model_reports,
            "selection": {
                "model": selected_model_name,
                "model_selection_metric": "validation_pr_auc",
                **threshold_report,
            },
            "trading_comparison": {
                "validation": {
                    "rule_based_all_signals": baseline_validation,
                    "ml_filtered": filtered_validation,
                },
                "test": {
                    "rule_based_all_signals": baseline_test,
                    "ml_filtered": filtered_test,
                },
            },
            "acceptance": {
                "dataset_schema_compatible": dataset["schema_version"]
                == ResearchFeatureDatasetProjection.SCHEMA_VERSION,
                "feature_leakage": quality["quality"]["leakage_check"]["status"]
                == "PASS",
                "chronological_split": split["readiness"] == "READY",
                "train_only_preprocessing": True,
                "model_training": True,
                "probability_output": True,
                "threshold_selection": True,
                "validation_metrics_generated": True,
                "test_metrics_generated": True,
                "trading_metrics_generated": True,
                "production_isolation": True,
            },
        }
