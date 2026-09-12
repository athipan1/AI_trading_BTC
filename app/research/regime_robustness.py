from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.research.baseline_ml import BaselineMLResearch
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.model_rule_benchmark import BenchmarkConfig, ModelRuleBenchmark
from app.research.walk_forward import WalkForwardConfig


@dataclass(frozen=True)
class RegimeRobustnessConfig:
    minimum_segment_selected_trades: int = 10
    minimum_segment_fold_count: int = 2
    robust_positive_fold_ratio: float = 0.75
    promising_positive_fold_ratio: float = 0.50
    minimum_profit_factor: float = 1.0
    minimum_attribution_coverage: float = 0.95
    maximum_unknown_selected_rate: float = 0.05


class RegimeRobustnessResearch(ModelRuleBenchmark):
    """Phase 5.5 regime robustness and failure-attribution diagnostics."""

    SCHEMA_VERSION = "regime_robustness_schema_v1"

    def __init__(
        self,
        *,
        baseline: BaselineMLResearch | None = None,
        walk_forward_config: WalkForwardConfig | None = None,
        benchmark_config: BenchmarkConfig | None = None,
        robustness_config: RegimeRobustnessConfig | None = None,
    ) -> None:
        super().__init__(
            baseline=baseline,
            walk_forward_config=walk_forward_config,
            benchmark_config=benchmark_config,
        )
        self.robustness_config = robustness_config or RegimeRobustnessConfig()

    @staticmethod
    def _segment_key(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get("strategy_id") or "UNKNOWN"),
            str(row.get("side") or "UNKNOWN").lower(),
            str(row.get("entry_market_regime") or "UNKNOWN"),
        )

    @classmethod
    def _fold_rows(cls, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            groups[int(row.get("fold") or 0)].append(row)

        result: list[dict[str, Any]] = []
        for fold in sorted(groups):
            comparison = cls._comparison(groups[fold])
            result.append({"fold": fold, **comparison})
        return result

    def _classify_segment(
        self,
        comparison: dict[str, Any],
        fold_rows: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]]:
        ml = comparison["ml_filtered"]
        selected = int(ml["trade_count"])
        expectancy = self._safe_float(ml.get("expectancy_r"))
        profit_factor = self._safe_float(ml.get("profit_factor"))
        fold_expectancies = [
            float(row["ml_filtered"]["expectancy_r"])
            for row in fold_rows
            if row["ml_filtered"]["expectancy_r"] is not None
            and int(row["ml_filtered"]["trade_count"]) > 0
        ]
        positive_folds = sum(value > 0 for value in fold_expectancies)
        positive_ratio = positive_folds / len(fold_expectancies) if fold_expectancies else 0.0
        sample_sufficient = (
            selected >= self.robustness_config.minimum_segment_selected_trades
            and len(fold_expectancies) >= self.robustness_config.minimum_segment_fold_count
        )

        diagnostics = {
            "sample_sufficient": sample_sufficient,
            "selected_trades": selected,
            "fold_count_with_selected_trades": len(fold_expectancies),
            "positive_expectancy_folds": positive_folds,
            "positive_expectancy_fold_ratio": positive_ratio,
            "mean_fold_expectancy_r": (
                float(np.mean(fold_expectancies)) if fold_expectancies else None
            ),
            "worst_fold_expectancy_r": min(fold_expectancies) if fold_expectancies else None,
            "expectancy_stddev_r": (
                float(np.std(fold_expectancies)) if fold_expectancies else None
            ),
        }

        if not sample_sufficient:
            return "INSUFFICIENT", diagnostics
        if expectancy is None or expectancy <= 0:
            return "FAILURE", diagnostics
        if (
            profit_factor is not None
            and profit_factor > self.robustness_config.minimum_profit_factor
            and positive_ratio >= self.robustness_config.robust_positive_fold_ratio
        ):
            return "ROBUST", diagnostics
        if (
            profit_factor is not None
            and profit_factor > self.robustness_config.minimum_profit_factor
            and positive_ratio >= self.robustness_config.promising_positive_fold_ratio
        ):
            return "PROMISING", diagnostics
        return "UNSTABLE", diagnostics

    def _composite_segments(
        self,
        observations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            groups[self._segment_key(row)].append(row)

        result: list[dict[str, Any]] = []
        for key in sorted(groups):
            current = groups[key]
            comparison = self._comparison(current)
            folds = self._fold_rows(current)
            classification, diagnostics = self._classify_segment(comparison, folds)
            strategy_id, side, regime = key
            result.append(
                {
                    "segment": f"{strategy_id}|{side}|{regime}",
                    "strategy_id": strategy_id,
                    "side": side,
                    "entry_market_regime": regime,
                    "classification": classification,
                    "diagnostics": diagnostics,
                    "folds": folds,
                    **comparison,
                }
            )
        return result

    @staticmethod
    def _is_unknown(row: dict[str, Any]) -> bool:
        return any(
            str(row.get(name) or "UNKNOWN").upper() == "UNKNOWN"
            for name in ("strategy_id", "side", "entry_market_regime")
        )

    @staticmethod
    def _classification_counts(segments: list[dict[str, Any]]) -> dict[str, int]:
        counts = {name: 0 for name in ("ROBUST", "PROMISING", "UNSTABLE", "FAILURE", "INSUFFICIENT")}
        for row in segments:
            classification = str(row.get("classification") or "")
            if classification in counts:
                counts[classification] += 1
        return counts

    def run(self, historical_trades: list[dict[str, Any]]) -> dict[str, Any]:
        phase54 = super().run(historical_trades)

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
        phase53 = super(ModelRuleBenchmark, self).run(historical_trades)
        if len(folds) != len(phase53["folds"]):
            raise ValueError("Phase 5.3 fold count changed during Phase 5.5 attribution")

        observations: list[dict[str, Any]] = []
        for fold, phase53_fold in zip(folds, phase53["folds"], strict=True):
            observations.extend(self._observations_for_fold(fold, phase53_fold))

        segments = self._composite_segments(observations)
        counts = self._classification_counts(segments)

        selected = [row for row in observations if bool(row.get("ml_selected"))]
        attributed = [row for row in selected if not self._is_unknown(row)]
        attribution_coverage = len(attributed) / len(selected) if selected else 0.0
        unknown_selected_rate = 1.0 - attribution_coverage if selected else 0.0

        failures = sorted(
            [row for row in segments if row["classification"] == "FAILURE"],
            key=lambda row: float(row["ml_filtered"]["total_realized_r"]),
        )
        strongest = sorted(
            [
                row
                for row in segments
                if row["classification"] in {"ROBUST", "PROMISING"}
            ],
            key=lambda row: float(row["ml_filtered"]["total_realized_r"]),
            reverse=True,
        )

        causal_regime_contract = (
            "entry_market_regime" in ResearchFeatureDatasetProjection.CATEGORICAL_FEATURES
        )
        source_acceptance = phase54["acceptance"]
        acceptance = {
            "chronological_integrity": bool(source_acceptance["chronological_integrity"]),
            "feature_leakage": bool(source_acceptance["feature_leakage"]),
            "production_isolation": bool(source_acceptance["production_isolation"]),
            "causal_regime_contract": causal_regime_contract,
            "failure_attribution_coverage": (
                attribution_coverage >= self.robustness_config.minimum_attribution_coverage
            ),
            "unknown_selected_rate": (
                unknown_selected_rate
                <= self.robustness_config.maximum_unknown_selected_rate
            ),
            "robust_or_promising_segment_exists": (
                counts["ROBUST"] + counts["PROMISING"] > 0
            ),
        }
        status = "PASS" if all(acceptance.values()) else "FAIL"

        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.5",
            "research_only": True,
            "production_position_store_mutated": False,
            "method": "regime_robustness_and_failure_attribution",
            "random_shuffle": False,
            "optimization_performed": False,
            "source_phase": {
                "phase": phase54["phase"],
                "schema_version": phase54["schema_version"],
                "acceptance_status": phase54["acceptance_status"],
            },
            "config": {
                "minimum_segment_selected_trades": self.robustness_config.minimum_segment_selected_trades,
                "minimum_segment_fold_count": self.robustness_config.minimum_segment_fold_count,
                "robust_positive_fold_ratio": self.robustness_config.robust_positive_fold_ratio,
                "promising_positive_fold_ratio": self.robustness_config.promising_positive_fold_ratio,
                "minimum_profit_factor": self.robustness_config.minimum_profit_factor,
                "minimum_attribution_coverage": self.robustness_config.minimum_attribution_coverage,
                "maximum_unknown_selected_rate": self.robustness_config.maximum_unknown_selected_rate,
            },
            "attribution": {
                "selected_trades": len(selected),
                "attributed_selected_trades": len(attributed),
                "failure_attribution_coverage": attribution_coverage,
                "unknown_selected_rate": unknown_selected_rate,
                "classification_counts": counts,
            },
            "segments": segments,
            "strongest_segments": strongest,
            "failure_segments": failures,
            "acceptance": acceptance,
            "acceptance_status": status,
        }
