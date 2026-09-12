from __future__ import annotations

from pathlib import Path

import pytest

from app.research.forward_oos import ForwardOOSAccumulator, ForwardOOSConfig
from app.research.historical_store import HistoricalResearchStore


def _trade(order_id: str, timestamp_ms: int, realized_r: float = 1.0) -> dict[str, object]:
    return {
        "order_id": order_id,
        "created_at": "2026-09-02T01:00:00+00:00",
        "entry_feature_timestamp_ms": timestamp_ms,
        "strategy_id": "triple_ema",
        "side": "buy",
        "entry_market_regime": "BULL_TREND",
        "realized_r": realized_r,
        "historical_replay": True,
    }


def test_evidence_stage_thresholds() -> None:
    research = ForwardOOSAccumulator()

    assert research.evidence_stage(0) == "TOO_EARLY"
    assert research.evidence_stage(19) == "TOO_EARLY"
    assert research.evidence_stage(20) == "EARLY_SIGNAL"
    assert research.evidence_stage(49) == "EARLY_SIGNAL"
    assert research.evidence_stage(50) == "INTERMEDIATE"
    assert research.evidence_stage(99) == "INTERMEDIATE"
    assert research.evidence_stage(100) == "STRONGER_EVIDENCE"


def test_accumulation_window_keeps_warmup_before_fresh_boundary() -> None:
    research = ForwardOOSAccumulator(
        config=ForwardOOSConfig(
            boundary_iso="2026-09-01T00:00:00+00:00",
            warmup_hours=300,
        )
    )

    since_ms, boundary_ms, until_ms = research.accumulation_window(
        "2026-09-12T00:00:00+00:00"
    )

    assert boundary_ms - since_ms == 300 * 60 * 60 * 1000
    assert until_ms > boundary_ms


def test_immutable_oos_store_filters_deduplicates_and_never_updates(tmp_path: Path) -> None:
    store = HistoricalResearchStore(tmp_path / "oos.json")
    boundary = 1_788_220_800_000
    replay = {
        "schema_version": "historical_replay_schema_v1",
        "trades": [
            _trade("before", boundary - 1),
            _trade("fresh", boundary + 1),
        ],
    }

    first = store.append_immutable_replay(
        replay,
        dataset_run_id="run-1",
        minimum_entry_feature_timestamp_ms=boundary,
        git_commit="abc",
    )
    second = store.append_immutable_replay(
        replay,
        dataset_run_id="run-2",
        minimum_entry_feature_timestamp_ms=boundary,
        git_commit="def",
    )

    assert first == {
        "inserted": 1,
        "duplicate_skipped": 0,
        "filtered_before_boundary": 1,
        "total": 1,
    }
    assert second == {
        "inserted": 0,
        "duplicate_skipped": 1,
        "filtered_before_boundary": 1,
        "total": 1,
    }
    stored = store.load()
    assert len(stored) == 1
    assert stored[0]["dataset_run_id"] == "run-1"
    assert stored[0]["git_commit"] == "abc"


def test_immutable_oos_store_rejects_conflicting_duplicate(tmp_path: Path) -> None:
    store = HistoricalResearchStore(tmp_path / "oos.json")
    boundary = 1_788_220_800_000
    original = {
        "schema_version": "historical_replay_schema_v1",
        "trades": [_trade("fresh", boundary + 1, realized_r=1.0)],
    }
    changed = {
        "schema_version": "historical_replay_schema_v1",
        "trades": [_trade("fresh", boundary + 1, realized_r=-1.0)],
    }

    store.append_immutable_replay(
        original,
        dataset_run_id="run-1",
        minimum_entry_feature_timestamp_ms=boundary,
    )

    with pytest.raises(ValueError, match="immutable research trade conflict"):
        store.append_immutable_replay(
            changed,
            dataset_run_id="run-2",
            minimum_entry_feature_timestamp_ms=boundary,
        )
