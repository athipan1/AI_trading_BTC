"""Phase 5.7.4 read-only audit of immutable Candidate V2 research evidence.

Does not repair data, write evidence, retune, or grant trading permissions.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.research.candidate_v2_forward import CandidateV2ForwardAccumulator
from app.research.candidate_v2_research import CandidateV2Research
from app.research.historical_replay import HistoricalStrategyReplay
from app.research.historical_store import HistoricalResearchStore


class CandidateV2IntegrityAuditor:
    SCHEMA_VERSION = "candidate_v2_integrity_v1"
    STATE_SCHEMA_VERSION = "candidate_v2_audit_state_v1"

    @staticmethod
    def _read(path: Path, *, optional: bool = False) -> dict[str, Any] | None:
        if not path.exists():
            if optional:
                return None
            raise ValueError(f"missing research artifact: {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"invalid research artifact: {path.name}")
        return payload

    @classmethod
    def _store(cls, path: Path) -> list[dict[str, Any]]:
        data = cls._read(path, optional=True)
        if data is None:
            return []
        if data.get("schema_version") != HistoricalResearchStore.SCHEMA_VERSION:
            raise ValueError("invalid OOS store schema")
        trades = data.get("trades")
        if not isinstance(trades, list) or any(not isinstance(t, dict) for t in trades):
            raise ValueError("OOS trades must all be objects")
        return trades

    @staticmethod
    def _verified_trade(trade: dict[str, Any]) -> None:
        try:
            quantity = float(trade["quantity"])
            risk = float(trade["initial_risk_usdt"])
            entry = float(trade["entry_fill_price"])
            exit_price = float(trade["exit_fill_price"])
            entry_fee = float(trade["entry_commission_usdt"])
            exit_fee = float(trade["exit_commission_usdt"])
            realized = float(trade["realized_r"])
            side = str(trade["side"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("incomplete replay trade accounting") from exc
        values = (quantity, risk, entry, exit_price, entry_fee, exit_fee, realized)
        if not all(math.isfinite(x) for x in values):
            raise ValueError("non-finite trade accounting")
        if quantity <= 0 or risk <= 0 or entry <= 0 or exit_price <= 0:
            raise ValueError("invalid positive trade accounting")
        if entry_fee < 0 or exit_fee < 0 or side not in {"buy", "sell"}:
            raise ValueError("invalid trade fees/side")
        signed = 1 if side == "buy" else -1
        expected = ((exit_price - entry) * quantity * signed - entry_fee - exit_fee) / risk
        if not math.isclose(realized, expected, rel_tol=1e-7, abs_tol=1e-7):
            raise ValueError("realized-R inconsistent with fills and fees")

    @staticmethod
    def _ids(trades: list[dict[str, Any]]) -> dict[str, str]:
        result: dict[str, str] = {}
        for trade in trades:
            key = str(trade.get("order_id") or "")
            if not key or key in result:
                raise ValueError("empty or duplicate OOS order_id")
            result[key] = CandidateV2ForwardAccumulator._hash(trade)
        return result

    @staticmethod
    def _check_timestamp(value: Any, label: str) -> datetime:
        return CandidateV2ForwardAccumulator._parse_time(value, label)

    def inspect(
        self,
        *,
        manifest_path: str | Path,
        candidate_store_path: str | Path,
        baseline_store_path: str | Path,
        checkpoint_path: str | Path,
        previous_state: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Return a sanitized audit and next independent lineage state, never mutate sources."""
        now = (now or datetime.now(UTC)).astimezone(UTC)
        manifest_file = Path(manifest_path)
        candidate_file = Path(candidate_store_path)
        baseline_file = Path(baseline_store_path)
        checkpoint_file = Path(checkpoint_path)
        issues: list[str] = []
        counts = {"candidate_v2_closed": 0, "canonical_rule_based_closed": 0}
        pin_hash: str | None = None
        policy_name: str | None = None
        last_until: str | None = None
        run_count = 0
        store_fingerprints: dict[str, dict[str, str]] = {"candidate": {}, "baseline": {}}
        next_state: dict[str, Any] | None = None
        checkpoint_present = checkpoint_file.exists()
        try:
            manifest = self._read(manifest_file)
            assert manifest is not None
            # Reuse the frozen manifest hash/policy hash check from Phase 5.7.2.
            CandidateV2Research().forward_validate([], manifest=manifest)
            forward = CandidateV2ForwardAccumulator()
            forward._preflight_manifest(manifest)
            pin = forward._pin(manifest)
            frozen = self._check_timestamp(manifest["frozen_at"], "frozen_at")
            if frozen > now:
                raise ValueError("frozen_at cannot lie in future")
            pin_hash = str(manifest["manifest_hash"])
            policy_name = str(manifest["selected_policy"]["name"])
            candidate = self._store(candidate_file)
            baseline = self._store(baseline_file)
            counts = {
                "candidate_v2_closed": len(candidate),
                "canonical_rule_based_closed": len(baseline),
            }
            run_id = f"phase573-v2-{pin_hash[:16]}"
            forward._check_store(candidate, prefix="candidate_v2_", frozen=frozen, expected_run_id=run_id)
            forward._check_store(baseline, prefix="triple_ema", frozen=frozen, expected_run_id=run_id)
            for trade in (*candidate, *baseline):
                self._verified_trade(trade)
                decision = self._check_timestamp(trade["decision_at"], "decision_at")
                timestamp_ms = trade.get("entry_feature_timestamp_ms")
                if type(timestamp_ms) is not int or timestamp_ms != int(decision.timestamp() * 1000):
                    raise ValueError("entry features are not timestamp-pinned")
                closed = self._check_timestamp(trade["closed_at"], "closed_at")
                if closed > now:
                    raise ValueError("future-dated trade close")
            store_fingerprints = {"candidate": self._ids(candidate), "baseline": self._ids(baseline)}
            checkpoint = self._read(checkpoint_file, optional=True)
            if checkpoint is None:
                if candidate or baseline or candidate_file.exists() or baseline_file.exists():
                    raise ValueError("evidence exists without checkpoint")
            else:
                if checkpoint.get("schema_version") != forward.CHECKPOINT_SCHEMA_VERSION:
                    raise ValueError("invalid V2 checkpoint schema")
                if checkpoint.get("frozen_pin") != pin:
                    raise ValueError("V2 checkpoint frozen pin mismatch")
                raw_count = checkpoint.get("run_count")
                if type(raw_count) is not int or raw_count < 1:
                    raise ValueError("invalid V2 checkpoint run_count")
                run_count = raw_count
                last_until = str(checkpoint.get("last_processed_until") or "")
                until = self._check_timestamp(last_until, "last_processed_until")
                if until > now.replace(minute=0, second=0, microsecond=0):
                    raise ValueError("checkpoint points into unfinished H1")
                if any(self._check_timestamp(t["closed_at"], "closed_at") > until for t in (*candidate, *baseline)):
                    raise ValueError("evidence extends beyond checkpoint H1 boundary")
                if (checkpoint.get("candidate_trade_count") != len(candidate)
                    or checkpoint.get("baseline_trade_count") != len(baseline)):
                    raise ValueError("checkpoint OOS counts mismatch")
                if (checkpoint.get("candidate_store_hash") != forward._hash(candidate)
                    or checkpoint.get("baseline_store_hash") != forward._hash(baseline)):
                    raise ValueError("checkpoint/store hash mismatch")
            if previous_state is not None:
                if previous_state.get("schema_version") != self.STATE_SCHEMA_VERSION:
                    raise ValueError("invalid previous V2 audit state")
                if previous_state.get("manifest_hash") != pin_hash:
                    raise ValueError("V2 manifest differs from previously verified audit")
                if run_count < previous_state.get("run_count", 0):
                    raise ValueError("checkpoint run_count rollback")
                previous_until = previous_state.get("last_processed_until")
                if previous_until and (not last_until or self._check_timestamp(last_until, "until")
                                       < self._check_timestamp(previous_until, "previous_until")):
                    raise ValueError("checkpoint H1 boundary rollback")
                prior_ids = previous_state.get("trade_fingerprints")
                if not isinstance(prior_ids, dict):
                    raise ValueError("previous evidence fingerprint map missing")
                for label, values in store_fingerprints.items():
                    old = prior_ids.get(label)
                    if not isinstance(old, dict):
                        raise ValueError("previous fingerprint set invalid")
                    if any(values.get(k) != v for k, v in old.items()):
                        raise ValueError("previously audited trade changed or disappeared")
            next_state = {
                "schema_version": self.STATE_SCHEMA_VERSION,
                "manifest_hash": pin_hash,
                "run_count": run_count,
                "last_processed_until": last_until,
                "trade_fingerprints": store_fingerprints,
            }
        except (OSError, ValueError, KeyError, TypeError, AssertionError, OverflowError) as exc:
            # Report stable error codes rather than leaking raw file content to the API.
            issues.append(type(exc).__name__ + ":" + str(exc)[:180])
        state = "FAIL" if issues else "PASS" if checkpoint_present else "WAITING"
        return ({
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.7.4",
            "read_only": True,
            "integrity_state": state,
            "issues": issues,
            "manifest_hash": pin_hash,
            "policy_name": policy_name,
            "counts": counts,
            "checkpoint": {"run_count": run_count, "last_processed_until": last_until},
            "promotion_allowed": False,
            "research_only": True,
        }, next_state if not issues else None)