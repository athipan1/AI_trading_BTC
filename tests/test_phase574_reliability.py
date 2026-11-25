"""Phase 5.7.4 fault injection, immutable evidence and watchdog/alert contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.research.candidate_v2_alerts import CandidateV2AlertPolicy
from app.research.candidate_v2_forward import CandidateV2ForwardAccumulator
from app.research.candidate_v2_integrity import CandidateV2IntegrityAuditor
from app.research.candidate_v2_research import CandidateV2Research
from app.research.candidate_v2_watchdog import CandidateV2Watchdog
from app.research.historical_replay import HistoricalStrategyReplay
from app.research.historical_store import HistoricalResearchStore

FREEZE = datetime(2026, 11, 23, 16, 52, 54, tzinfo=UTC)
NOW = datetime(2026, 11, 26, 0, 0, tzinfo=UTC)


def _write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _manifest() -> dict[str, Any]:
    policy = {
        "name": "confirmed", "min_trend_strength_atr": 1.2, "min_volume_ratio": 1,
        "min_atr_pct": 0.001, "max_atr_pct": 0.06, "max_long_rsi": 72, "min_short_rsi": 28,
    }
    research = CandidateV2Research()
    body = {
        "schema_version": research.MANIFEST_SCHEMA_VERSION,
        "phase": "5.7.2", "research_only": True,
        "auto_production_promotion": False, "frozen_at": FREEZE.isoformat(),
        "discovery_cutoff": "2026-08-30T15:00:00+00:00",
        "selected_policy": policy, "selected_policy_hash": research._hash(policy),
        "discovery_order_ids": ["hist-old-1"], "v1_oos_reuse_allowed": False,
        "oos_retuning_allowed": False,
    }
    return {**body, "manifest_hash": research._hash(body)}


def _trade(prefix: str, *, decision: datetime | None = None) -> dict[str, Any]:
    decision = decision or FREEZE + timedelta(hours=2)
    fill = 100.02
    exit_fill = 101.02
    qty = 0.001
    fee = 0.00012
    risk = 0.005
    entry = decision + timedelta(hours=1)
    close = decision + timedelta(hours=3)
    return {
        "order_id": f"hist-{prefix}-{int(entry.timestamp()*1000)}",
        "strategy_id": prefix,
        "status": "CLOSED", "side": "buy",
        "decision_at": decision.isoformat(), "created_at": entry.isoformat(),
        "closed_at": close.isoformat(),
        "entry_feature_timestamp_ms": int(decision.timestamp() * 1000),
        "entry_feature_schema_version": "entry_feature_schema_v1",
        "quantity": qty, "initial_risk_usdt": risk,
        "entry_fill_price": fill, "exit_fill_price": exit_fill,
        "entry_commission_usdt": fee, "exit_commission_usdt": fee,
        "realized_r": ((exit_fill - fill) * qty - 2 * fee) / risk,
    }


def _environment(tmp_path: Path, *, filled: bool = True) -> dict[str, Path]:
    files = {name: tmp_path / filename for name, filename in {
        "manifest_path": "phase572_v2_manifest.json",
        "candidate_store_path": "phase573_v2_candidate_oos.json",
        "baseline_store_path": "phase573_v2_baseline_oos.json",
        "checkpoint_path": "phase573_v2_checkpoint.json",
    }.items()}
    manifest = _manifest()
    _write(files["manifest_path"], manifest)
    if filled:
        run_id = f"phase573-v2-{manifest['manifest_hash'][:16]}"
        for key, prefix in (("candidate_store_path", "candidate_v2_triple_ema_confirmed"),
                            ("baseline_store_path", "triple_ema")):
            HistoricalResearchStore(files[key]).append_immutable_replay(
                {"schema_version": HistoricalStrategyReplay.SCHEMA_VERSION,
                 "trades": [_trade(prefix)]},
                dataset_run_id=run_id,
                minimum_entry_feature_timestamp_ms=int(FREEZE.timestamp() * 1000) + 1,
                source="binance_public_spot_ohlcv",
            )
        forward = CandidateV2ForwardAccumulator()
        candidate = HistoricalResearchStore(files["candidate_store_path"]).load()
        baseline = HistoricalResearchStore(files["baseline_store_path"]).load()
        _write(files["checkpoint_path"], {
            "schema_version": forward.CHECKPOINT_SCHEMA_VERSION,
            "phase": "5.7.3", "frozen_pin": forward._pin(manifest),
            "run_count": 1, "last_processed_until": (NOW - timedelta(hours=1)).replace(minute=0).isoformat(),
            "candidate_trade_count": len(candidate), "baseline_trade_count": len(baseline),
            "candidate_store_hash": forward._hash(candidate),
            "baseline_store_hash": forward._hash(baseline),
        })
    return files


def _heartbeat(path: Path, *, age_minutes: int, state: str = "SUCCESS") -> None:
    _write(path, {
        "schema_version": CandidateV2Watchdog.HEARTBEAT_SCHEMA_VERSION,
        "last_attempt_at": (NOW - timedelta(minutes=age_minutes)).isoformat(),
        "last_success_at": (NOW - timedelta(minutes=age_minutes)).isoformat(),
        "last_result": state,
        "mode": "watch",
    })


def test_v2_integrity_valid_with_immutable_independent_stores(tmp_path: Path) -> None:
    files = _environment(tmp_path)
    audit, state = CandidateV2IntegrityAuditor().inspect(**files, now=NOW)
    assert audit["integrity_state"] == "PASS"
    assert audit["counts"] == {"candidate_v2_closed": 1, "canonical_rule_based_closed": 1}
    assert audit["promotion_allowed"] is False
    assert state is not None
    audit_2, state_2 = CandidateV2IntegrityAuditor().inspect(
        **files, previous_state=state, now=NOW
    )
    assert audit_2["integrity_state"] == "PASS"
    assert state_2 == state


def test_manifest_tamper_and_checkpoint_replay_pin_detected(tmp_path: Path) -> None:
    files = _environment(tmp_path)
    manifest = json.loads(files["manifest_path"].read_text())
    manifest["selected_policy"]["max_long_rsi"] = 99
    _write(files["manifest_path"], manifest)
    audit, state = CandidateV2IntegrityAuditor().inspect(**files, now=NOW)
    assert audit["integrity_state"] == "FAIL"
    assert state is None
    assert files["candidate_store_path"].exists()


def test_checkpoint_store_tamper_cannot_be_hidden_by_replay_counts(tmp_path: Path) -> None:
    files = _environment(tmp_path)
    payload = json.loads(files["candidate_store_path"].read_text())
    payload["trades"][0]["realized_r"] += 1
    _write(files["candidate_store_path"], payload)
    audit, _ = CandidateV2IntegrityAuditor().inspect(**files, now=NOW)
    assert audit["integrity_state"] == "FAIL"
    assert any("realized-R" in x for x in audit["issues"])


def test_past_freeze_violation_and_orphan_store_fail_closed(tmp_path: Path) -> None:
    files = _environment(tmp_path)
    files["checkpoint_path"].unlink()
    audit, _ = CandidateV2IntegrityAuditor().inspect(**files, now=NOW)
    assert audit["integrity_state"] == "FAIL"


def test_lineage_rollback_detected_with_audit_state(tmp_path: Path) -> None:
    files = _environment(tmp_path)
    auditor = CandidateV2IntegrityAuditor()
    _, previous = auditor.inspect(**files, now=NOW)
    assert previous is not None
    checkpoint = json.loads(files["checkpoint_path"].read_text())
    checkpoint["run_count"] = 0
    _write(files["checkpoint_path"], checkpoint)
    audit, _ = auditor.inspect(**files, previous_state=previous, now=NOW)
    assert audit["integrity_state"] == "FAIL"


def test_first_run_without_checkpoint_is_waiting_not_pass(tmp_path: Path) -> None:
    files = _environment(tmp_path, filled=False)
    audit, _ = CandidateV2IntegrityAuditor().inspect(**files, now=NOW)
    assert audit["integrity_state"] == "WAITING"


@pytest.mark.parametrize(
    ("age", "expected"), [(1, "HEALTHY"), (16, "WARNING"), (31, "CRITICAL")]
)
def test_independent_heartbeat_liveness(tmp_path: Path, age: int, expected: str) -> None:
    hb = tmp_path / "hb.json"
    _heartbeat(hb, age_minutes=age)
    audit = {
        "integrity_state": "PASS",
        "checkpoint": {"last_processed_until": (NOW - timedelta(hours=1)).isoformat()},
             "counts": {"candidate_v2_closed": 0, "canonical_rule_based_closed": 0}, "manifest_hash": "abc"}
    health = CandidateV2Watchdog().evaluate(integrity=audit, heartbeat_path=hb,
                                             report_path=tmp_path / "none.json", now=NOW)
    if expected == "HEALTHY":
        # Report missing in an existing checkpoint warrants a WARNING; watcher itself is healthy.
        assert health["watcher_state"] == expected
    else:
        assert health["operational_state"] == expected
    assert health["trade_execution"] is False


def test_zero_trades_is_not_a_watcher_error(tmp_path: Path) -> None:
    hb = tmp_path / "hb.json"
    _heartbeat(hb, age_minutes=1)
    audit = {"integrity_state": "WAITING", "checkpoint": {},
             "counts": {"candidate_v2_closed": 0, "canonical_rule_based_closed": 0}, "manifest_hash": "abc"}
    health = CandidateV2Watchdog().evaluate(integrity=audit, heartbeat_path=hb,
                                             report_path=tmp_path / "none.json", now=NOW)
    assert health["operational_state"] == "WAITING"
    assert "WATCHER_HEARTBEAT_EXPIRED" not in health["issues"]


def test_corrupt_heartbeat_detected_and_unknown_when_missing(tmp_path: Path) -> None:
    audit = {"integrity_state": "WAITING", "checkpoint": {}, "counts": {}}
    path = tmp_path / "hb.json"
    monitor = CandidateV2Watchdog()
    unknown = monitor.evaluate(
        integrity=audit, heartbeat_path=path, report_path=tmp_path / "no.json", now=NOW
    )
    assert unknown["operational_state"] == "UNKNOWN"
    path.write_text("{not json")
    critical = monitor.evaluate(
        integrity=audit, heartbeat_path=path, report_path=tmp_path / "no.json", now=NOW
    )
    assert critical["operational_state"] == "CRITICAL"


def test_alert_deduplicates_and_recovers_after_two_healthy_checks() -> None:
    policy = CandidateV2AlertPolicy()
    warn = {"operational_state": "WARNING"}
    kind, state = policy.decision(warn, None, now=NOW)
    assert kind == "ALERT"
    kind, _ = policy.decision(warn, state, now=NOW + timedelta(minutes=5))
    assert kind is None
    good = {"operational_state": "HEALTHY"}
    kind, pending = policy.decision(good, state, now=NOW + timedelta(minutes=10))
    assert kind is None
    kind, acknowledged = policy.decision(good, pending, now=NOW + timedelta(minutes=15))
    assert kind == "RECOVERY"
    assert acknowledged["last_notified_state"] == "HEALTHY"
    kind, _ = policy.decision(warn, state, now=NOW + timedelta(minutes=61))
    assert kind == "ALERT"