"""Phase 5.7.3 closed-candle, post-freeze, replay and idempotency guards."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.market_data.service import MarketDataError
from app.models import Candle
from app.research.binance_public_ohlcv import BinancePublicOHLCV
from app.research.candidate_v2 import POLICIES
from app.research.candidate_v2_forward import CandidateV2ForwardAccumulator
from app.research.candidate_v2_research import CandidateV2Research
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import HistoricalStrategyReplay
from app.research.historical_store import HistoricalResearchStore

FREEZE = datetime(2026, 11, 23, 16, 52, 54, tzinfo=UTC)
FRESH = datetime(2026, 11, 23, 17, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 24, 12, 15, tzinfo=UTC)


def _manifest() -> dict[str, Any]:
    research = CandidateV2Research()
    policy = POLICIES[1].to_dict()
    body = {
        "schema_version": research.MANIFEST_SCHEMA_VERSION,
        "phase": "5.7.2",
        "research_only": True,
        "auto_production_promotion": False,
        "frozen_at": FREEZE.isoformat(),
        "discovery_cutoff": "2026-08-30T15:00:00+00:00",
        "selected_policy": policy,
        "selected_policy_hash": research._hash(policy),
        "discovery_order_ids": ["hist-old-discovery-0"],
        "v1_oos_reuse_allowed": False,
        "oos_retuning_allowed": False,
    }
    return {**body, "manifest_hash": research._hash(body)}


def _trade(strategy_id: str, decision: datetime, *, side: str = "buy") -> dict[str, Any]:
    buy = side == "buy"
    entry_fill = 100.02 if buy else 99.98
    exit_fill = 101.0 if buy else 99.0
    quantity = 0.001
    fee = 0.00012
    risk = 0.005
    realized = ((exit_fill - entry_fill) * (1 if buy else -1) * quantity - 2 * fee) / risk
    entry = decision + timedelta(hours=1)
    closed = decision + timedelta(hours=3)
    return {
        "order_id": f"hist-{strategy_id}-{int(entry.timestamp() * 1000)}",
        "strategy_id": strategy_id,
        "symbol": "BTC/USDT",
        "side": side,
        "status": "CLOSED",
        "entry_market_regime": "BULL_TREND" if buy else "BEAR_TREND",
        "decision_at": decision.isoformat(),
        "created_at": entry.isoformat(),
        "closed_at": closed.isoformat(),
        "opened_at_ms": int(entry.timestamp() * 1000),
        "entry_feature_schema_version": "entry_feature_schema_v1",
        "entry_feature_timestamp_ms": int(decision.timestamp() * 1000),
        "entry_features": {
            "trend_strength_atr": 1.8,
            "volume_ratio_20": 1.3,
            "atr_pct": 0.01,
            "rsi_14": 65 if buy else 40,
            "ema20_slope_3": 0.002 if buy else -0.002,
            "ema50_slope_3": 0.001 if buy else -0.001,
        },
        "entry_price": 100.0,
        "entry_fill_price": entry_fill,
        "exit_price": 100.98 if buy else 99.02,
        "exit_fill_price": exit_fill,
        "quantity": quantity,
        "initial_stop_loss": 95.0 if buy else 105.0,
        "initial_risk_price_distance": 5.0,
        "initial_risk_usdt": risk,
        "trade_path_highest_price": max(entry_fill, exit_fill),
        "trade_path_lowest_price": min(entry_fill, exit_fill),
        "trade_path_observation_count": 3,
        "holding_seconds": 7200.0,
        "entry_commission_usdt": fee,
        "exit_commission_usdt": fee,
        "total_commission_usdt": fee * 2,
        "realized_r": realized,
        "net_realized_pnl": realized * risk,
    }


class FakeCandles(HistoricalMarketDataService):
    def __init__(self, *, missing: bool = False) -> None:
        super().__init__()
        self.calls = 0
        self.missing = missing

    def fetch_range(
        self, symbol: str, timeframe: str, *, since_ms: int, until_ms: int, page_limit: int = 1000
    ) -> list[Candle]:
        assert symbol == "BTC/USDT" and timeframe == "1h"
        self.calls += 1
        times = list(range(since_ms, until_ms, 3_600_000))
        if self.missing:
            times.pop(50)
        return [
            Candle(timestamp_ms=t, open=100.0, close=100.0, high=101.0, low=99.0, volume=10.0)
            for t in times
        ]


def _paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "candidate_store_path": tmp_path / "phase573_v2_candidate.json",
        "baseline_store_path": tmp_path / "phase573_v2_baseline.json",
        "checkpoint_path": tmp_path / "phase573_v2_checkpoint.json",
    }


def _fake_replay(self, segments, strategy):
    del self, segments
    strategy_id = strategy.strategy_id
    # A position opened before freeze but closed after freeze must not be counted.
    old = _trade(strategy_id, FREEZE.replace(minute=0, second=0))
    new = _trade(strategy_id, FRESH)
    return {"trades": [old, new], "closed_trades": 2}


def test_pre_freeze_replay_trade_is_discarded_and_replay_is_independent(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(HistoricalStrategyReplay, "replay_segments", _fake_replay)
    data = FakeCandles()
    paths = _paths(tmp_path)
    worker = CandidateV2ForwardAccumulator()
    result = worker.run(manifest=_manifest(), market_data=data, now=NOW, **paths)
    assert result["state"] == "ACCUMULATING"
    assert result["counts"]["candidate_v2_closed"] == 2
    assert result["counts"]["canonical_rule_based_closed"] == 2
    assert result["market_data"]["candidate_new_trades"] == 2
    assert result["comparison"]["candidate_v2_full_replay"]["trade_count"] == 2
    assert result["promotion_allowed"] is False
    assert result["production_mutation"] is False
    assert result["forward_validation"]["promotion_allowed"] is False
    assert all(
        datetime.fromisoformat(t["decision_at"]) > FREEZE
        for t in HistoricalResearchStore(paths["candidate_store_path"]).load()
    )
    assert data.calls == 1

    before = [path.read_bytes() for path in paths.values()]
    repeated = worker.run(manifest=_manifest(), market_data=data, now=NOW, **paths)
    assert repeated["state"] == "NO_NEW_CANDLES"
    assert data.calls == 1
    assert before == [path.read_bytes() for path in paths.values()]


def test_no_new_closed_h1_does_not_touch_network_or_create_evidence(tmp_path: Path) -> None:
    data = FakeCandles()
    report = CandidateV2ForwardAccumulator().run(
        manifest=_manifest(), market_data=data, now=FREEZE + timedelta(minutes=1), **_paths(tmp_path)
    )
    assert report["state"] == "AWAITING_CLOSED_H1"
    assert data.calls == 0
    assert list(tmp_path.iterdir()) == []


def test_manifest_tampering_fails_before_fetch_or_writes(tmp_path: Path) -> None:
    data = FakeCandles()
    manifest = _manifest()
    manifest["selected_policy"]["min_volume_ratio"] = 0.0
    with pytest.raises(ValueError, match="manifest hash"):
        CandidateV2ForwardAccumulator().run(
            manifest=manifest, market_data=data, now=NOW, **_paths(tmp_path)
        )
    assert data.calls == 0
    assert list(tmp_path.iterdir()) == []


def test_gap_fails_closed_without_creating_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(HistoricalStrategyReplay, "replay_segments", _fake_replay)
    with pytest.raises(ValueError, match="incomplete/gapped"):
        CandidateV2ForwardAccumulator().run(
            manifest=_manifest(), market_data=FakeCandles(missing=True), now=NOW, **_paths(tmp_path)
        )
    assert list(tmp_path.iterdir()) == []


def test_v1_store_contamination_refused(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = HistoricalResearchStore(paths["candidate_store_path"])
    store.upsert_replay(
        {"schema_version": "historical_replay_schema_v1", "trades": [_trade("triple_ema", FRESH)]},
        dataset_run_id="old-v1-data",
    )
    data = FakeCandles()
    with pytest.raises(ValueError, match="foreign/duplicate"):
        CandidateV2ForwardAccumulator().run(
            manifest=_manifest(), market_data=data, now=NOW, **paths
        )
    assert data.calls == 0
    assert not paths["checkpoint_path"].exists()


def test_invalid_costs_and_until_are_rejected(tmp_path: Path) -> None:
    from app.research.candidate_v2_forward import CandidateV2ForwardConfig

    with pytest.raises(ValueError, match="fee_rate"):
        CandidateV2ForwardAccumulator(config=CandidateV2ForwardConfig(fee_rate=0))
    with pytest.raises(ValueError, match="warmup"):
        CandidateV2ForwardAccumulator(config=CandidateV2ForwardConfig(warmup_hours=200))
    with pytest.raises(ValueError, match="unfinished"):
        CandidateV2ForwardAccumulator().run(
            manifest=_manifest(), market_data=FakeCandles(), now=NOW,
            requested_until="2026-11-25T00:00:00+00:00", **_paths(tmp_path)
        )


def test_checkpoint_pin_and_integrity_protect_existing_evidence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(HistoricalStrategyReplay, "replay_segments", _fake_replay)
    paths = _paths(tmp_path)
    worker = CandidateV2ForwardAccumulator()
    worker.run(manifest=_manifest(), market_data=FakeCandles(), now=NOW, **paths)
    checkpoint = json.loads(paths["checkpoint_path"].read_text())
    checkpoint["frozen_pin"]["replay"]["slippage_bps"] = 5
    paths["checkpoint_path"].write_text(json.dumps(checkpoint))
    with pytest.raises(ValueError, match="checkpoint frozen policy"):
        worker.run(manifest=_manifest(), market_data=FakeCandles(), now=NOW, **paths)
    checkpoint["frozen_pin"]["replay"]["slippage_bps"] = 2
    paths["checkpoint_path"].write_text(json.dumps(checkpoint))
    trades = json.loads(paths["candidate_store_path"].read_text())
    trades["trades"][0]["realized_r"] = -10
    paths["candidate_store_path"].write_text(json.dumps(trades))
    with pytest.raises(ValueError, match="checkpoint/store tampering"):
        worker.run(manifest=_manifest(), market_data=FakeCandles(), now=NOW, **paths)


def test_conflicting_replay_revision_detected_before_any_append(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(HistoricalStrategyReplay, "replay_segments", _fake_replay)
    paths = _paths(tmp_path)
    worker = CandidateV2ForwardAccumulator()
    worker.run(manifest=_manifest(), market_data=FakeCandles(), now=NOW, **paths)
    candidate_before = paths["candidate_store_path"].read_bytes()
    baseline_before = paths["baseline_store_path"].read_bytes()

    def changed(self, segments, strategy):
        response = _fake_replay(self, segments, strategy)
        response["trades"][1]["exit_fill_price"] = 102.0
        return response

    monkeypatch.setattr(HistoricalStrategyReplay, "replay_segments", changed)
    with pytest.raises(ValueError, match="reported realized_r does not match|immutable OOS replay conflict"):
        worker.run(
            manifest=_manifest(), market_data=FakeCandles(), now=NOW + timedelta(hours=1),
            **paths,
        )
    assert candidate_before == paths["candidate_store_path"].read_bytes()
    assert baseline_before == paths["baseline_store_path"].read_bytes()


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


class FakeHTTPSession:
    def __init__(self, rows: list[list[Any]]) -> None:
        self.rows = rows
        self.requests: list[dict[str, Any]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: int) -> FakeResponse:
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        start = params["startTime"]
        end = params["endTime"]
        rows = [r for r in self.rows if start <= r[0] <= end]
        return FakeResponse(rows[: params["limit"]])


def test_public_binance_h1_pagination_does_not_require_keys() -> None:
    hour = 3_600_000
    rows = [
        [i * hour, "100", "102", "99", "101", "1.2", (i + 1) * hour - 1]
        for i in range(5)
    ]
    session = FakeHTTPSession(rows)
    candles = BinancePublicOHLCV(session=session).fetch_range(
        "BTC/USDT", "1h", since_ms=0, until_ms=5 * hour, page_limit=2
    )
    assert [c.timestamp_ms for c in candles] == [i * hour for i in range(5)]
    assert len(session.requests) == 3
    assert all(r["url"].startswith("https://data-api.binance.vision/") for r in session.requests)
    assert all("apiKey" not in r["params"] for r in session.requests)


def test_invalid_public_ohlcv_fails_closed() -> None:
    hour = 3_600_000
    invalid = [[0, "100", "102", "99", "101", "1", 10]]
    with pytest.raises(MarketDataError, match="close timestamp"):
        BinancePublicOHLCV(session=FakeHTTPSession(invalid)).fetch_range(
            "BTC/USDT", "1h", since_ms=0, until_ms=hour
        )
    with pytest.raises(ValueError, match="only supports"):
        BinancePublicOHLCV(session=FakeHTTPSession([])).fetch_range(
            "ETH/USDT", "1h", since_ms=0, until_ms=hour
        )


def test_empty_replay_accumulates_no_phantom_trades(monkeypatch, tmp_path: Path) -> None:
    def nothing(self, segments, strategy):
        del self, segments, strategy
        return {"trades": [], "closed_trades": 0}

    monkeypatch.setattr(HistoricalStrategyReplay, "replay_segments", nothing)
    paths = _paths(tmp_path)
    result = CandidateV2ForwardAccumulator().run(
        manifest=_manifest(), market_data=FakeCandles(), now=NOW, **paths
    )
    assert result["state"] == "AWAITING_CLOSED_V2_TRADES"
    assert result["counts"]["candidate_v2_closed"] == 0
    assert result["forward_validation"]["state"] == "AWAITING_FRESH_OOS"
    assert result["comparison"]["candidate_v2_full_replay"]["trade_count"] == 0
    assert json.loads(paths["checkpoint_path"].read_text())["run_count"] == 1


def test_accumulator_rejects_non_v2_artifact_paths(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths["baseline_store_path"] = tmp_path / "phase56_v1_evidence.json"
    with pytest.raises(ValueError, match="dedicated phase573_v2"):
        CandidateV2ForwardAccumulator().run(
            manifest=_manifest(), market_data=FakeCandles(), now=NOW, **paths
        )


def test_watcher_lock_refuses_concurrent_runs(tmp_path: Path) -> None:
    from scripts.run_phase573_fresh_oos import _exclusive_watcher_lock

    checkpoint = tmp_path / "phase573_v2_checkpoint.json"
    with _exclusive_watcher_lock(checkpoint):
        with pytest.raises(RuntimeError, match="already running"):
            with _exclusive_watcher_lock(checkpoint):
                pass