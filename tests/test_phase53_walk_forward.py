from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.research.baseline_ml import BaselineMLConfig, BaselineMLResearch
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.walk_forward import WalkForwardConfig, WalkForwardResearch


def _rows(count: int = 120) -> list[dict[str, object]]:
    start = datetime(2021, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for index in range(count):
        profitable = index % 4 == 0 or index % 7 == 0
        features: dict[str, object] = {}
        for name in ResearchFeatureDatasetProjection.CATEGORICAL_FEATURES:
            if name == "strategy_id":
                features[name] = "triple_ema"
            elif name == "side":
                features[name] = "buy"
            else:
                features[name] = "BULL_TREND"
        for offset, name in enumerate(ResearchFeatureDatasetProjection.NUMERIC_FEATURES):
            features[name] = float((index % 17) + offset + (5 if profitable else 0))
        timestamp = (start + timedelta(hours=index)).isoformat()
        rows.append(
            {
                "order_id": f"wf-{index:04d}",
                "feature_available_at": timestamp,
                "execution_time": timestamp,
                "features": features,
                "targets": {"realized_r": 1.5 if profitable else -0.75},
            }
        )
    return rows


def test_walk_forward_windows_are_expanding_and_chronological() -> None:
    research = WalkForwardResearch(
        config=WalkForwardConfig(
            fold_count=3,
            initial_train_fraction=0.40,
            validation_fraction=0.10,
            test_fraction=0.10,
        )
    )
    folds = research._folds(_rows())

    assert len(folds) == 3
    assert [len(fold["train"]) for fold in folds] == [48, 72, 96]
    assert all(len(fold["validation"]) == 12 for fold in folds)
    assert all(len(fold["test"]) == 12 for fold in folds)
    for fold in folds:
        assert fold["train"][-1]["feature_available_at"] < fold["validation"][0][
            "feature_available_at"
        ]
        assert fold["validation"][-1]["feature_available_at"] < fold["test"][0][
            "feature_available_at"
        ]


def test_walk_forward_run_preserves_research_isolation(monkeypatch) -> None:
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
    research = WalkForwardResearch(
        baseline=baseline,
        config=WalkForwardConfig(
            fold_count=3,
            initial_train_fraction=0.40,
            validation_fraction=0.10,
            test_fraction=0.10,
            minimum_test_selected_trades=1,
        ),
    )
    report = research.run([])

    assert report["phase"] == "5.3"
    assert report["method"] == "expanding_walk_forward"
    assert report["random_shuffle"] is False
    assert report["acceptance_status"] == "PASS"
    assert report["production_position_store_mutated"] is False
    assert report["aggregate"]["fold_count"] == 3
    assert len(report["folds"]) == 3
    assert all(
        fold["selection"]["threshold_selection_scope"] == "validation_only"
        for fold in report["folds"]
    )
