"""Phase 5.7.2 immutable, cost-aware discovery and post-freeze OOS controls."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.models import MarketRegime, TradeAction, TradeSignal
from app.research.candidate_v2 import POLICIES, CandidateV2ReplayStrategy
from app.research.candidate_v2_research import CandidateV2Research
from app.research.historical_store import HistoricalResearchStore

FREEZE = datetime(2026, 11, 23, tzinfo=UTC)


def _trade(i: int, *, start: datetime | None = None) -> dict[str, object]:
    start = start or datetime(2025, 1, 1, tzinfo=UTC)
    t = start + timedelta(hours=i * 4)
    buy = i % 2 == 0
    side = "buy" if buy else "sell"
    quality = i % 4 == 0 or i % 7 == 0
    profit = quality or i % 8 == 1
    entry_fill = 100.02 if buy else 99.98
    exit_fill = (100.34 if profit else 99.64) if buy else (99.66 if profit else 100.36)
    quantity = 0.001
    fees = 0.00012
    risk = 0.005
    realized_r = ((exit_fill - entry_fill) * quantity * (1 if buy else -1) - fees * 2) / risk
    decision_ms = int(t.timestamp() * 1000)
    return {
        "order_id": f"hist-test-{i}-{decision_ms}",
        "status": "CLOSED",
        "strategy_id": "triple_ema" if buy else "triple_ema_short",
        "symbol": "BTC/USDT",
        "side": side,
        "entry_market_regime": "BULL_TREND" if buy else "BEAR_TREND",
        "data_origin": "historical_replay",
        "entry_feature_schema_version": "entry_feature_schema_v1",
        "entry_feature_timestamp_ms": decision_ms,
        "decision_at": t.isoformat(),
        "created_at": (t + timedelta(hours=1)).isoformat(),
        "closed_at": (t + timedelta(hours=2)).isoformat(),
        "entry_price": 100.0,
        "entry_fill_price": entry_fill,
        "exit_price": 100.32 if buy and profit else (
            99.66 if buy else (99.68 if profit else 100.34)
        ),
        "exit_fill_price": exit_fill,
        "quantity": quantity,
        "initial_stop_loss": 95.0 if buy else 105.0,
        "initial_risk_price_distance": 5.0,
        "initial_risk_usdt": risk,
        "trade_path_highest_price": max(entry_fill, exit_fill),
        "trade_path_lowest_price": min(entry_fill, exit_fill),
        "trade_path_observation_count": 2,
        "holding_seconds": 3600.0,
        "entry_commission_usdt": fees,
        "exit_commission_usdt": fees,
        "total_commission_usdt": 2 * fees,
        "realized_r": realized_r,
        "net_realized_pnl": realized_r * risk,
        "entry_features": {
            "rsi_14": 65 if buy else 40,
            "atr_pct": 0.01,
            "atr_14": 1.0,
            "ema20_slope_3": 0.002 if buy else -0.002,
            "ema50_slope_3": 0.001 if buy else -0.001,
            "trend_strength_atr": 1.5 if quality else 0.6,
            "volume_ratio_20": 1.2 if quality else 0.8,
        },
    }


def _study(size: int = 180) -> tuple[dict[str, object], dict[str, object]]:
    researcher = CandidateV2Research()
    return researcher.discover([_trade(i) for i in range(size)], frozen_at=FREEZE)


def test_policy_filters_only_entry_time_features() -> None:
    basic, confirmed = POLICIES
    good = _trade(0)["entry_features"]
    assert isinstance(good, dict)
    assert basic.passes(good, side="buy", regime="BULL_TREND")
    assert confirmed.passes(good, side="buy", regime="BULL_TREND")
    assert not basic.passes({"realized_r": 100}, side="buy", regime="BULL_TREND")
    assert not basic.passes(good, side="buy", regime="BEAR_TREND")
    assert not confirmed.passes(_trade(2)["entry_features"], side="buy", regime="BULL_TREND")


def test_discovery_freezes_after_purged_walk_forward_and_holdout() -> None:
    report, manifest = _study()
    assert report["candidate_status"] == "FROZEN_RESEARCH_ONLY"
    assert report["future_oos_required"] is True
    assert len(report["folds"]) == 3
    assert all(f["validation_end_before_test_start"] for f in report["folds"])
    assert all(f["train_last_close_before_validation"] for f in report["folds"])
    assert report["holdout"]["trade_count"] == 36
    assert manifest["selected_policy"]["name"] in {"balanced", "confirmed"}
    assert manifest["v1_oos_reuse_allowed"] is False
    assert manifest["auto_production_promotion"] is False


def test_discovery_rejects_lookahead_and_missing_costs() -> None:
    trades = [_trade(i) for i in range(180)]
    trades[0]["decision_at"] = "2025-01-01T06:00:00+00:00"
    with pytest.raises(ValueError, match="timestamps violate"):
        CandidateV2Research().discover(trades, frozen_at=FREEZE)
    trades = [_trade(i) for i in range(180)]
    trades[0]["realized_r"] = 100
    with pytest.raises(ValueError, match="does not match"):
        CandidateV2Research().discover(trades, frozen_at=FREEZE)


def test_discovery_rejects_duplicate_ids_and_exclusions() -> None:
    trades = [_trade(i) for i in range(180)]
    trades[-1]["order_id"] = trades[0]["order_id"]
    with pytest.raises(ValueError, match="duplicate"):
        CandidateV2Research().discover(trades, frozen_at=FREEZE)
    trades = [_trade(i) for i in range(180)]
    trades[10]["status"] = "OPEN"
    with pytest.raises(ValueError, match="excluded"):
        CandidateV2Research().discover(trades, frozen_at=FREEZE)


def test_no_use_of_v1_oos_during_discovery() -> None:
    report, manifest = _study()
    assert report["production_promotion_allowed"] is False
    assert "oos_store" not in manifest
    assert manifest["discovery_cutoff"] < manifest["frozen_at"]


def test_forward_rejects_reused_old_oos_and_overlapping_ids() -> None:
    _, manifest = _study()
    old = [_trade(300)]
    with pytest.raises(ValueError, match="strictly after"):
        CandidateV2Research().forward_validate(old, manifest=manifest)
    duplicate = [_trade(0, start=FREEZE + timedelta(days=2))]
    # IDs include decision timestamp, so force the original discovery ID.
    duplicate[0]["order_id"] = manifest["discovery_order_ids"][0]
    with pytest.raises(ValueError, match="overlaps discovery"):
        CandidateV2Research().forward_validate(duplicate, manifest=manifest)


def test_forward_only_after_freeze_cannot_promote() -> None:
    _, manifest = _study()
    future = [_trade(i, start=FREEZE + timedelta(days=2)) for i in range(60)]
    result = CandidateV2Research().forward_validate(future, manifest=manifest)
    assert result["state"] == "RESEARCH_EVIDENCE_ONLY"
    assert result["future_signals"] == 60
    assert result["source_provenance"]["net_realized_r_verified"] is True
    assert result["promotion_allowed"] is False
    assert result["oos_retuning_performed"] is False


def test_empty_forward_is_waiting() -> None:
    _, manifest = _study()
    result = CandidateV2Research().forward_validate([], manifest=manifest)
    assert result["state"] == "AWAITING_FRESH_OOS"
    assert result["promotion_allowed"] is False


def test_manifest_tamper_is_rejected() -> None:
    _, manifest = _study()
    manifest["selected_policy"]["min_volume_ratio"] = 0.0
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        CandidateV2Research().forward_validate([], manifest=manifest)


def test_missing_feature_fails_closed() -> None:
    trades = [_trade(i) for i in range(180)]
    for trade in trades:
        trade["entry_features"].pop("rsi_14")
    with pytest.raises(ValueError, match="no predeclared policy"):
        CandidateV2Research().discover(trades, frozen_at=FREEZE)


def test_invalid_fold_size_fails_closed() -> None:
    with pytest.raises(ValueError, match="insufficient discovery"):
        CandidateV2Research().discover([_trade(i) for i in range(20)], frozen_at=FREEZE)


def test_study_from_real_historical_store_contract(tmp_path: Path) -> None:
    store = HistoricalResearchStore(tmp_path / "history.json")
    store.upsert_replay(
        {"schema_version": "historical_replay_schema_v1", "trades": [_trade(i) for i in range(180)]},
        dataset_run_id="predeclared-discovery",
    )
    study, manifest = CandidateV2Research().discover(store.load(), frozen_at=FREEZE)
    assert study["source_provenance"]["qualified_trades"] == 180
    assert manifest["entry_feature_schema_version"] == "entry_feature_schema_v1"
    assert json.loads((tmp_path / "history.json").read_text())["trades"]


class _EntryStub:
    strategy_id = "triple_ema"
    min_candles = 201

    def __init__(self, action: TradeAction) -> None:
        self.action = action

    def analyze(self, candles, symbol, timeframe) -> TradeSignal:
        return TradeSignal(
            action=self.action,
            symbol=symbol,
            timeframe=timeframe,
            confidence=0.5,
            regime=MarketRegime.BULL_TREND,
            entry_price=100.0,
            stop_loss=95.0,
        )


def test_replay_adapter_preserves_exit(monkeypatch) -> None:
    from app.research import candidate_v2

    monkeypatch.setattr(candidate_v2, "build_entry_time_features", lambda _: {"atr_pct": None})
    filtered = CandidateV2ReplayStrategy(_EntryStub(TradeAction.BUY), POLICIES[0])
    signal = filtered.analyze([], "BTC/USDT", "1h")
    assert signal.action == TradeAction.HOLD
    assert signal.stop_loss is None
    exit_signal = CandidateV2ReplayStrategy(_EntryStub(TradeAction.EXIT), POLICIES[0]).analyze(
        [], "BTC/USDT", "1h"
    )
    assert exit_signal.action == TradeAction.EXIT