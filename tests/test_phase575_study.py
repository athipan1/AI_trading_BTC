"""Phase 5.7.5 discovery scope, offline provenance and legacy-vs-stress pairing."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.models import Candle
from app.research.candidate_v2 import POLICIES
from app.research.candidate_v2_research import CandidateV2Research
from app.research.execution_realism import ExecutionRealismConfig
from app.research.execution_realism_study import ExecutionRealismStudy
from scripts.run_phase575_execution_realism import _load_candles, main

START = datetime(2026, 6, 1, tzinfo=UTC)
HOUR_MS = 3_600_000


def _candles(count: int = 210) -> list[Candle]:
    start_ms = int(START.timestamp() * 1000)
    return [
        Candle(
            timestamp_ms=start_ms + i * HOUR_MS,
            open=100, high=101, low=99, close=100, volume=1,
        ) for i in range(count)
    ]


def _manifest() -> dict:
    policy = POLICIES[1].to_dict()
    body = {
        "schema_version": CandidateV2Research.MANIFEST_SCHEMA_VERSION,
        "phase": "5.7.2",
        "research_only": True,
        "auto_production_promotion": False,
        "frozen_at": "2026-11-23T16:52:54+00:00",
        "discovery_cutoff": "2026-08-30T15:00:00+00:00",
        "selected_policy": policy,
        "selected_policy_hash": CandidateV2Research._hash(policy),
        "discovery_order_ids": ["hist-old-discovery-0"],
        "v1_oos_reuse_allowed": False,
        "oos_retuning_allowed": False,
    }
    return {**body, "manifest_hash": CandidateV2Research._hash(body)}


def test_discovery_only_side_by_side_report_is_research_only() -> None:
    candles = _candles()
    start = candles[0].timestamp_ms
    report = ExecutionRealismStudy().run(
        candles=candles,
        manifest=_manifest(),
        config=ExecutionRealismConfig(),
        since_ms=start,
        until_ms=start + len(candles) * HOUR_MS,
    )
    assert report["schema_version"] == "phase575_execution_realism_study_v1"
    assert report["data_scope"] == "HISTORICAL_DISCOVERY_ONLY_NOT_FRESH_OOS"
    assert report["promotion_allowed"] is False
    assert report["trade_execution"] is False
    assert report["production_mutation"] is False
    assert report["ohlcv_integrity"]["complete_range"] is True
    assert report["selected_policy_name"] == "confirmed"
    assert set(report["comparisons"]) == {
        "triple_ema", "triple_ema_short",
        "candidate_v2_triple_ema_confirmed", "candidate_v2_triple_ema_short_confirmed",
    }
    for comparison in report["comparisons"].values():
        assert "legacy" in comparison and "realism" in comparison


def test_manifest_hash_edit_fail_closed() -> None:
    candles = _candles()
    manifest = _manifest()
    manifest["selected_policy"]["max_long_rsi"] = 999
    with pytest.raises(ValueError):
        ExecutionRealismStudy().run(
            candles=candles,
            manifest=manifest,
            config=ExecutionRealismConfig(),
            since_ms=candles[0].timestamp_ms,
            until_ms=candles[-1].timestamp_ms + HOUR_MS,
        )


def test_refuses_future_oos_for_candidates() -> None:
    candles = _candles()
    with pytest.raises(ValueError, match="post-discovery/OOS"):
        ExecutionRealismStudy().run(
            candles=candles,
            manifest=_manifest(),
            config=ExecutionRealismConfig(),
            since_ms=candles[0].timestamp_ms,
            until_ms=int(datetime(2026, 9, 1, tzinfo=UTC).timestamp() * 1000),
        )


def test_missing_ohlcv_and_bad_endpoints_refused() -> None:
    candles = _candles()
    with pytest.raises(ValueError, match="missing range endpoints"):
        ExecutionRealismStudy().run(
            candles=candles,
            manifest=_manifest(),
            config=ExecutionRealismConfig(),
            since_ms=candles[0].timestamp_ms,
            until_ms=candles[-1].timestamp_ms + 3 * HOUR_MS,
        )
    with pytest.raises(ValueError, match="gaps forbidden"):
        gaps = [*candles[:90], *candles[91:]]
        ExecutionRealismStudy().run(
            candles=gaps,
            manifest=_manifest(),
            config=ExecutionRealismConfig(),
            since_ms=candles[0].timestamp_ms,
            until_ms=candles[-1].timestamp_ms + HOUR_MS,
        )


def test_cli_offline_report_is_new_and_never_overwrites(monkeypatch, tmp_path: Path) -> None:
    candles = _candles()
    until = START + timedelta(hours=len(candles))
    input_path = tmp_path / "phase575_ohlcv.json"
    input_path.write_text(json.dumps({
        "schema_version": "phase575_ohlcv_v1",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "candles": [c.model_dump() for c in candles],
    }), encoding="utf-8")
    manifest_path = tmp_path / "phase572_v2_manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    report = tmp_path / "phase575_offline_stress.json"
    monkeypatch.setattr(sys, "argv", [
        "phase575", "--since", START.isoformat(), "--until", until.isoformat(),
        "--manifest", str(manifest_path), "--ohlcv-json", str(input_path),
        "--report", str(report),
    ])
    assert main() == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["source"] == "explicit_offline_phase575_ohlcv_v1"
    assert payload["promotion_allowed"] is False
    with pytest.raises(FileExistsError):
        main()


def test_trade_history_store_is_not_valid_ohlcv_input(tmp_path: Path) -> None:
    path = tmp_path / "historical.json"
    path.write_text(json.dumps({
        "schema_version": "historical_research_store_v1", "trades": [],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="not a research trade store"):
        _load_candles(path)