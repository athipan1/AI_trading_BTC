from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.research.baseline_ml import BaselineMLConfig, BaselineMLResearch
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.model_rule_benchmark import BenchmarkConfig, ModelRuleBenchmark
from app.research.walk_forward import WalkForwardConfig


def _rows(count: int = 160) -> list[dict[str, object]]:
    start = datetime(2021, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for index in range(count):
        profitable = index % 4 == 0 or index % 9 == 0
        features: dict[str, object] = {}
        for name in ResearchFeatureDatasetProjection.CATEGORICAL_FEATURES:
            if name == "strategy_id":
                features[name] = "triple_ema" if index % 2 == 0 else "triple_ema_short"
            elif name == "side":
                features[name] = "buy" if index % 2 == 0 else "sell"
            else:
                features[name] = "BULL_TREND" if index % 3 else "BEAR_TREND"
        for offset, name in enumerate(ResearchFeatureDatasetProjection.NUMERIC_FEATURES):
            features[name] = float((index % 17) + offset + (6 if profitable else 0))
        timestamp = (start + timedelta(hours=index)).isoformat()
        rows.append(
            {
                "order_id": f"bench-{index:04d}",
                "feature_available_at": timestamp,
                "execution_time": timestamp,
                "features": features,
                "targets": {"realized_r": 1.6 if profitable else -0.7},
            }
        )
    return rows


def test_phase54_metrics_include_profit_factor_and_drawdown() -> None:
    observations = [
        {"realized_r": 1.0, "ml_selected": True},
        {"realized_r": -0.5, "ml_selected": True},
        {"realized_r": -0.75, "ml_selected": False},
        {"realized_r": 2.0, "ml_selected": True},
    ]

    comparison = ModelRuleBenchmark._comparison(observations)

    assert comparison["rule_based"]["trade_count"] == 4
    assert comparison["ml_filtered"]["trade_count"] == 3
    assert comparison["ml_filtered"]["selection_rate_pct"] == 75.0
    assert comparison["ml_filtered"]["profit_factor"] == 6.0
    assert comparison["ml_filtered"]["max_drawdown_r"] == 0.5


def test_phase54_groups_strategy_side_regime_and_year(monkeypatch) -> None:
    rows = _rows()

    def fake_quality(cls, positions, **kwargs):
        return {
            "readiness": {"training": "READY"},
            "quality": {"leakage_check": {"status": "PASS"}},
        }

    def fake_build(cls, positions, **kwargs):
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "feature_contract": {},
            "rows": rows,
        }

    monkeypatch.setattr(
        ResearchFeatureDatasetProjection,
        "quality",
        classmethod(fake_quality),
    )
    monkeypatch.setattr(
        ResearchFeatureDatasetProjection,
        "build",
        classmethod(fake_build),
    )

    baseline = BaselineMLResearch(
        BaselineMLConfig(
            minimum_validation_selection=2,
            threshold_start=0.30,
            threshold_stop=0.70,
            threshold_step=0.10,
        )
    )
    benchmark = ModelRuleBenchmark(
        baseline=baseline,
        walk_forward_config=WalkForwardConfig(
            fold_count=3,
            initial_train_fraction=0.40,
            validation_fraction=0.10,
            test_fraction=0.10,
            minimum_test_selected_trades=1,
        ),
        benchmark_config=BenchmarkConfig(
            minimum_positive_expectancy_fold_ratio=0.0,
            maximum_single_fold_positive_r_contribution=1.0,
            maximum_single_regime_positive_r_contribution=1.0,
            minimum_profit_factor=0.0,
            minimum_segment_selected_trades=1,
            require_drawdown_improvement=False,
        ),
    )

    report = benchmark.run([])

    assert report["phase"] == "5.4"
    assert report["research_only"] is True
    assert report["production_position_store_mutated"] is False
    assert report["random_shuffle"] is False
    assert report["source_phase"]["phase"] == "5.3"
    assert report["source_phase"]["acceptance_status"] == "PASS"
    assert len(report["segments"]["fold"]) == 3
    assert {row["segment"] for row in report["segments"]["strategy"]} == {
        "triple_ema",
        "triple_ema_short",
    }
    assert {row["segment"] for row in report["segments"]["side"]} == {"buy", "sell"}
    assert {row["segment"] for row in report["segments"]["market_regime"]} == {
        "BEAR_TREND",
        "BULL_TREND",
    }
    assert {row["segment"] for row in report["segments"]["year"]} == {"2021"}
    assert report["acceptance"]["production_isolation"] is True
    assert report["acceptance"]["feature_leakage"] is True
    assert report["acceptance"]["chronological_integrity"] is True
