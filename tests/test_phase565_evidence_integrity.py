from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.research.evidence_integrity import EvidenceIntegrityAuditor, EvidenceIntegrityConfig


NOW = datetime(2026, 9, 14, 1, 0, tzinfo=UTC)
BOUNDARY = "2026-09-01T00:00:00+00:00"
BOUNDARY_MS = int(datetime.fromisoformat(BOUNDARY).timestamp() * 1000)


def _manifest() -> dict[str, object]:
    return {
        "manifest_hash": "manifest-1",
        "policy_hash": "policy-1",
        "model_fingerprint": "model-1",
        "discovery_cutoff": "2026-08-30T15:00:00+00:00",
    }


def _trade(order_id: str, *, offset_hours: int = 1, pnl: float = 1.0) -> dict[str, object]:
    return {
        "order_id": order_id,
        "strategy_id": "triple_ema",
        "entry_feature_timestamp_ms": BOUNDARY_MS + offset_hours * 3_600_000,
        "realized_pnl": pnl,
        "data_origin": "historical_replay",
        "dataset_run_id": "phase565-test",
        "source": "binance_ohlcv",
    }


def _checkpoint(*, count: int = 2, run_count: int = 4) -> dict[str, object]:
    return {
        "schema_version": "forward_oos_checkpoint_schema_v1",
        "phase": "5.6.2",
        "frozen_pin": {
            **_manifest(),
            "boundary_iso": BOUNDARY,
            "warmup_hours": 288,
        },
        "last_processed_until": "2026-09-14T00:00:00+00:00",
        "last_oos_trade_count": count,
        "last_evidence_stage": "TOO_EARLY",
        "last_state": "TOO_EARLY",
        "run_count": run_count,
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    manifest = tmp_path / "manifest.json"
    store = tmp_path / "oos.json"
    checkpoint = tmp_path / "checkpoint.json"
    _write(manifest, _manifest())
    _write(
        store,
        {
            "schema_version": "historical_research_store_v1",
            "trades": [_trade("a"), _trade("b", offset_hours=2)],
        },
    )
    _write(checkpoint, _checkpoint())
    return manifest, store, checkpoint


def _auditor(*, stale_after_seconds: float = 108_000.0) -> EvidenceIntegrityAuditor:
    return EvidenceIntegrityAuditor(
        config=EvidenceIntegrityConfig(
            boundary_iso=BOUNDARY,
            stale_after_seconds=stale_after_seconds,
        ),
        now_factory=lambda: NOW,
    )


def test_clean_evidence_passes_and_builds_lineage_state(tmp_path: Path) -> None:
    manifest, store, checkpoint = _paths(tmp_path)

    report, state = _auditor().audit(
        manifest_path=manifest,
        oos_store_path=store,
        checkpoint_path=checkpoint,
    )

    assert report["state"] == "PASS"
    assert report["operational_state"] == "HEALTHY"
    assert report["integrity_ok"] is True
    assert all(report["checks"].values())
    assert report["evidence"]["oos_trade_count"] == 2
    assert state["run_count"] == 4
    assert set(state["trade_fingerprints"]) == {"a", "b"}
    assert report["research_only"] is True
    assert report["production_execution_mutated"] is False


def test_duplicate_order_id_fails_integrity(tmp_path: Path) -> None:
    manifest, store, checkpoint = _paths(tmp_path)
    _write(
        store,
        {
            "schema_version": "historical_research_store_v1",
            "trades": [_trade("dup"), _trade("dup", offset_hours=2)],
        },
    )

    report, _ = _auditor().audit(
        manifest_path=manifest,
        oos_store_path=store,
        checkpoint_path=checkpoint,
    )

    assert report["state"] == "FAIL"
    assert report["checks"]["order_ids_unique"] is False
    assert report["violations"]["duplicate_order_ids"] == ["dup"]


def test_checkpoint_count_mismatch_fails_integrity(tmp_path: Path) -> None:
    manifest, store, checkpoint = _paths(tmp_path)
    _write(checkpoint, _checkpoint(count=3))

    report, _ = _auditor().audit(
        manifest_path=manifest,
        oos_store_path=store,
        checkpoint_path=checkpoint,
    )

    assert report["checks"]["checkpoint_count_matches_store"] is False
    assert report["integrity_ok"] is False


def test_frozen_pin_drift_fails_integrity(tmp_path: Path) -> None:
    manifest, store, checkpoint = _paths(tmp_path)
    payload = _checkpoint()
    payload["frozen_pin"]["policy_hash"] = "tampered"
    _write(checkpoint, payload)

    report, _ = _auditor().audit(
        manifest_path=manifest,
        oos_store_path=store,
        checkpoint_path=checkpoint,
    )

    assert report["checks"]["frozen_pin_matches_manifest"] is False
    assert report["state"] == "FAIL"


def test_trade_before_frozen_boundary_fails_integrity(tmp_path: Path) -> None:
    manifest, store, checkpoint = _paths(tmp_path)
    early = _trade("early")
    early["entry_feature_timestamp_ms"] = BOUNDARY_MS - 1
    _write(
        store,
        {
            "schema_version": "historical_research_store_v1",
            "trades": [early, _trade("b", offset_hours=2)],
        },
    )

    report, _ = _auditor().audit(
        manifest_path=manifest,
        oos_store_path=store,
        checkpoint_path=checkpoint,
    )

    assert report["checks"]["all_trades_after_boundary"] is False
    assert report["violations"]["before_boundary_count"] == 1


def test_previous_lineage_detects_rollback_and_existing_trade_mutation(tmp_path: Path) -> None:
    manifest, store, checkpoint = _paths(tmp_path)
    auditor = _auditor()
    _, previous_state = auditor.audit(
        manifest_path=manifest,
        oos_store_path=store,
        checkpoint_path=checkpoint,
    )

    mutated = _trade("a", pnl=999.0)
    _write(
        store,
        {
            "schema_version": "historical_research_store_v1",
            "trades": [mutated],
        },
    )
    rolled_back = _checkpoint(count=1, run_count=3)
    rolled_back["last_processed_until"] = "2026-09-13T00:00:00+00:00"
    _write(checkpoint, rolled_back)

    report, _ = auditor.audit(
        manifest_path=manifest,
        oos_store_path=store,
        checkpoint_path=checkpoint,
        previous_state=previous_state,
    )

    assert report["checks"]["run_count_monotonic"] is False
    assert report["checks"]["oos_trade_count_monotonic"] is False
    assert report["checks"]["last_processed_until_monotonic"] is False
    assert report["checks"]["immutable_existing_trades"] is False
    assert report["violations"]["changed_existing_order_ids"] == ["a", "b"]


def test_stale_checkpoint_is_operational_warning_not_evidence_corruption(tmp_path: Path) -> None:
    manifest, store, checkpoint = _paths(tmp_path)

    report, _ = _auditor(stale_after_seconds=60).audit(
        manifest_path=manifest,
        oos_store_path=store,
        checkpoint_path=checkpoint,
    )

    assert report["integrity_ok"] is True
    assert report["state"] == "PASS"
    assert report["operational_state"] == "STALE"
