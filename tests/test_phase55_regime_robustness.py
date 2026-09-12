from __future__ import annotations

from typing import Any

from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.model_rule_benchmark import ModelRuleBenchmark
from app.research.regime_robustness import (
    RegimeRobustnessConfig,
    RegimeRobustnessResearch,
)
from app.research.walk_forward import WalkForwardResearch


def _comparison(expectancy: float, profit_factor: float, selected: int = 20) -> dict[str, Any]:
    return {
        "rule_based": {},
        "ml_filtered": {
            "trade_count": selected,
            "expectancy_r": expectancy,
            "profit_factor": profit_factor,
            "total_realized_r": expectancy * selected,
        },
        "expectancy_uplift_r": None,
    }


def _fold(expectancy: float, selected: int = 10) -> dict[str, Any]:
    return {
        "fold": 1,
        "rule_based": {},
        "ml_filtered": {
            "trade_count": selected,
            "expectancy_r": expectancy,
            "total_realized_r": expectancy * selected,
        },
        "expectancy_uplift_r": None,
    }


def test_segment_classification_distinguishes_robust_and_failure() -> None:
    research = RegimeRobustnessResearch(
        robustness_config=RegimeRobustnessConfig(
            minimum_segment_selected_trades=10,
            minimum_segment_fold_count=2,
        )
    )
    positive_folds = [_fold(0.4), {**_fold(0.6), "fold": 2}]
    negative_folds = [_fold(-0.4), {**_fold(-0.2), "fold": 2}]

    robust, diagnostics = research._classify_segment(
        _comparison(0.5, 1.5), positive_folds
    )
    failure, _ = research._classify_segment(
        _comparison(-0.3, 0.7), negative_folds
    )

    assert robust == "ROBUST"
    assert diagnostics["positive_expectancy_fold_ratio"] == 1.0
    assert failure == "FAILURE"


def test_composite_segments_attribute_strategy_side_regime() -> None:
    research = RegimeRobustnessResearch(
        robustness_config=RegimeRobustnessConfig(
            minimum_segment_selected_trades=4,
            minimum_segment_fold_count=2,
        )
    )
    observations: list[dict[str, Any]] = []
    for fold in (1, 2):
        for index in range(4):
            observations.append(
                {
                    "fold": fold,
                    "strategy_id": "triple_ema",
                    "side": "buy",
                    "entry_market_regime": "BULL_TREND",
                    "ml_selected": True,
                    "realized_r": 1.0 if index < 3 else -0.5,
                }
            )

    segments = research._composite_segments(observations)

    assert len(segments) == 1
    assert segments[0]["segment"] == "triple_ema|buy|BULL_TREND"
    assert segments[0]["classification"] == "ROBUST"
    assert segments[0]["diagnostics"]["fold_count_with_selected_trades"] == 2


def test_phase55_preserves_phase54_failure_and_production_isolation(monkeypatch) -> None:
    observations: list[dict[str, Any]] = []
    for fold in (1, 2):
        for index in range(10):
            observations.append(
                {
                    "fold": fold,
                    "strategy_id": "triple_ema",
                    "side": "buy",
                    "entry_market_regime": "BULL_TREND",
                    "ml_selected": True,
                    "realized_r": 1.0 if index < 7 else -0.5,
                }
            )

    def fake_phase54(self, historical_trades):
        return {
            "phase": "5.4",
            "schema_version": "model_rule_benchmark_schema_v1",
            "acceptance_status": "FAIL",
            "acceptance": {
                "chronological_integrity": True,
                "feature_leakage": True,
                "production_isolation": True,
            },
        }

    def fake_phase53(self, historical_trades):
        return {
            "phase": "5.3",
            "folds": [{"fold": 1}, {"fold": 2}],
        }

    def fake_build(cls, positions, **kwargs):
        return {"rows": [{"order_id": "a"}, {"order_id": "b"}]}

    def fake_folds(self, rows):
        return [
            {"fold": 1, "train": [], "validation": [], "test": []},
            {"fold": 2, "train": [], "validation": [], "test": []},
        ]

    def fake_observations(self, fold, phase53_fold):
        return [row for row in observations if row["fold"] == fold["fold"]]

    monkeypatch.setattr(ModelRuleBenchmark, "run", fake_phase54)
    monkeypatch.setattr(WalkForwardResearch, "run", fake_phase53)
    monkeypatch.setattr(
        ResearchFeatureDatasetProjection,
        "build",
        classmethod(fake_build),
    )
    monkeypatch.setattr(RegimeRobustnessResearch, "_folds", fake_folds)
    monkeypatch.setattr(
        RegimeRobustnessResearch,
        "_observations_for_fold",
        fake_observations,
    )

    research = RegimeRobustnessResearch(
        robustness_config=RegimeRobustnessConfig(
            minimum_segment_selected_trades=10,
            minimum_segment_fold_count=2,
        )
    )
    report = research.run([])

    assert report["phase"] == "5.5"
    assert report["source_phase"]["acceptance_status"] == "FAIL"
    assert report["optimization_performed"] is False
    assert report["production_position_store_mutated"] is False
    assert report["acceptance_status"] == "PASS"
    assert report["attribution"]["failure_attribution_coverage"] == 1.0
    assert report["attribution"]["classification_counts"]["ROBUST"] == 1
