"""Read-only walk-forward candidate selection with future-OOS embargo.

The Phase 5.7.2 signal-level counterfactual uses fee/slippage-adjusted
canonical historical replay trades. It is not a replacement for a complete
portfolio/exchange replay, and it cannot authorize order execution.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.research.candidate_v2 import POLICIES, EntryQualityPolicy
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.frozen_oos_validation import FrozenOOSValidationResearch


@dataclass(frozen=True)
class CandidateV2StudyConfig:
    fold_count: int = 3
    initial_train_fraction: float = 0.45
    validation_fraction: float = 0.08
    test_fraction: float = 0.08
    holdout_fraction: float = 0.20
    minimum_train_trades: int = 20
    minimum_validation_trades: int = 5
    minimum_test_trades: int = 5
    minimum_selected_validation: int = 3


@dataclass(frozen=True)
class PreparedTrade:
    order_id: str
    decision_time: datetime
    execution_time: datetime
    closed_time: datetime
    realized_r: float
    side: str
    regime: str
    features: dict[str, Any]


class CandidateV2Research:
    """Selection uses discovery validation slices only; Phase 5.6 OOS is never an input."""

    SCHEMA_VERSION = "candidate_v2_discovery_study_v1"
    MANIFEST_SCHEMA_VERSION = "candidate_v2_frozen_manifest_v1"
    FORWARD_SCHEMA_VERSION = "candidate_v2_fresh_oos_validation_v1"

    def __init__(
        self,
        config: CandidateV2StudyConfig | None = None,
        policies: tuple[EntryQualityPolicy, ...] = POLICIES,
    ) -> None:
        self.config = config or CandidateV2StudyConfig()
        if len(policies) < 1 or len({item.name for item in policies}) != len(policies):
            raise ValueError("candidate policies must be non-empty with unique names")
        if self.config.fold_count < 1:
            raise ValueError("fold_count must be positive")
        if not (0 < self.config.holdout_fraction < 0.5):
            raise ValueError("invalid holdout fraction")
        if not (0 < self.config.initial_train_fraction < 1):
            raise ValueError("invalid initial train fraction")
        if not (0 < self.config.validation_fraction < 1):
            raise ValueError("invalid validation fraction")
        if not (0 < self.config.test_fraction < 1):
            raise ValueError("invalid test fraction")
        if self.config.minimum_selected_validation < 1:
            raise ValueError("minimum_selected_validation must be positive")
        self.policies = policies

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _time(value: Any, name: str) -> datetime:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} is missing")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} is not ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{name} requires timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _number(value: Any, name: str, *, positive: bool = False) -> float:
        if isinstance(value, bool) or value is None:
            raise ValueError(f"{name} is missing")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} is not numeric") from exc
        if not math.isfinite(parsed) or (positive and parsed <= 0):
            raise ValueError(f"{name} is invalid")
        return parsed

    @classmethod
    def _prepare(cls, trades: list[dict[str, Any]]) -> tuple[list[PreparedTrade], dict[str, Any]]:
        if not trades:
            raise ValueError("historical research store has no trades")
        ids = [str(trade.get("order_id") or "") for trade in trades]
        if not all(ids) or len(ids) != len(set(ids)):
            raise ValueError("duplicate or empty order_id in historical research store")
        dataset = ResearchFeatureDatasetProjection.build(
            [], historical_trades=trades, source="historical"
        )
        rows = dataset.get("rows", [])
        if len(rows) != len(trades):
            raise ValueError("research feature projection excluded some trades (fail closed)")
        lookup = {str(row["order_id"]): row for row in rows}
        prepared: list[PreparedTrade] = []
        total_fees = 0.0
        total_slippage = 0.0
        for raw in trades:
            order_id = str(raw["order_id"])
            row = lookup.get(order_id)
            if row is None:
                raise ValueError(f"missing projected trade {order_id}")
            if raw.get("entry_feature_schema_version") != "entry_feature_schema_v1":
                raise ValueError("entry feature schema missing or unsupported")
            if str(raw.get("data_origin")) != "historical_replay":
                raise ValueError("candidate research requires canonical historical replay store")
            decision = cls._time(row.get("feature_available_at"), "feature_available_at")
            timestamp_ms = raw.get("entry_feature_timestamp_ms")
            if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
                raise ValueError("entry_feature_timestamp_ms is missing or invalid")
            if timestamp_ms != int(decision.timestamp() * 1000):
                raise ValueError("entry features are not pinned to the decision candle")
            execution = cls._time(row.get("execution_time"), "execution_time")
            closed = cls._time(raw.get("closed_at"), "closed_at")
            if not (decision <= execution <= closed):
                raise ValueError("trade timestamps violate decision <= execution <= closed")
            if not isinstance(row.get("features"), dict):
                raise ValueError("canonical entry features are missing")
            side = str(raw.get("side") or "").lower()
            if side not in {"buy", "sell"}:
                raise ValueError("unknown trade side")
            risk = cls._number(raw.get("initial_risk_usdt"), "initial_risk_usdt", positive=True)
            quantity = cls._number(raw.get("quantity"), "quantity", positive=True)
            entry_fill = cls._number(raw.get("entry_fill_price"), "entry_fill_price", positive=True)
            exit_fill = cls._number(raw.get("exit_fill_price"), "exit_fill_price", positive=True)
            entry_unfilled = cls._number(raw.get("entry_price"), "entry_price", positive=True)
            exit_unfilled = cls._number(raw.get("exit_price"), "exit_price", positive=True)
            entry_fee = cls._number(raw.get("entry_commission_usdt"), "entry_commission_usdt")
            exit_fee = cls._number(raw.get("exit_commission_usdt"), "exit_commission_usdt")
            if entry_fee < 0 or exit_fee < 0:
                raise ValueError("negative commissions")
            total_fees += entry_fee + exit_fee
            total_slippage += quantity * (
                abs(entry_fill - entry_unfilled) + abs(exit_fill - exit_unfilled)
            )
            direction = 1 if side == "buy" else -1
            computed_r = ((exit_fill - entry_fill) * quantity * direction - entry_fee - exit_fee) / risk
            realized_r = cls._number(row.get("targets", {}).get("realized_r"), "realized_r")
            if not math.isclose(computed_r, realized_r, rel_tol=1e-7, abs_tol=1e-7):
                raise ValueError("reported realized_r does not match fees and fill prices")
            prepared.append(
                PreparedTrade(
                    order_id=order_id,
                    decision_time=decision,
                    execution_time=execution,
                    closed_time=closed,
                    realized_r=realized_r,
                    side=side,
                    regime=str(raw.get("entry_market_regime") or ""),
                    features=row["features"],
                )
            )
        prepared.sort(key=lambda trade: (trade.decision_time, trade.order_id))
        if total_fees <= 0 or total_slippage <= 0:
            raise ValueError("candidate research requires positive fees and slippage in source replay")
        return prepared, {
            "qualified_trades": len(prepared),
            "recorded_fees_usdt": round(total_fees, 8),
            "recorded_slippage_usdt": round(total_slippage, 8),
            "net_realized_r_verified": True,
            "feature_schema": "entry_feature_schema_v1",
            "source": "historical_replay",
        }

    @staticmethod
    def _metrics(rows: list[PreparedTrade], policy: EntryQualityPolicy | None) -> dict[str, Any]:
        realized = np.asarray([trade.realized_r for trade in rows], dtype=float)
        selected = np.asarray(
            [
                policy is None
                or policy.passes(trade.features, side=trade.side, regime=trade.regime)
                for trade in rows
            ],
            dtype=bool,
        )
        return FrozenOOSValidationResearch._metrics(realized, selected)

    def _choose(self, rows: list[PreparedTrade]) -> EntryQualityPolicy:
        candidates = []
        for policy in self.policies:
            metrics = self._metrics(rows, policy)
            count = int(metrics["trade_count"])
            if count >= self.config.minimum_selected_validation:
                candidates.append((policy, metrics))
        if not candidates:
            raise ValueError("no predeclared policy reached minimum validation sample")
        # Only validation slices determine ranking; never inspect test/holdout outcomes here.
        return max(
            candidates,
            key=lambda item: (
                float(item[1]["total_realized_r"]),
                float(item[1]["expectancy_r"] or 0.0),
                -self.policies.index(item[0]),
            ),
        )[0]

    def _folds(
        self, rows: list[PreparedTrade]
    ) -> tuple[list[dict[str, Any]], list[PreparedTrade], list[PreparedTrade]]:
        holdout_size = max(1, math.ceil(len(rows) * self.config.holdout_fraction))
        pool = rows[:-holdout_size]
        holdout = rows[-holdout_size:]
        n = len(pool)
        start = max(self.config.minimum_train_trades, math.floor(n * self.config.initial_train_fraction))
        val_size = max(self.config.minimum_validation_trades, math.floor(n * self.config.validation_fraction))
        test_size = max(self.config.minimum_test_trades, math.floor(n * self.config.test_fraction))
        if start + self.config.fold_count * (val_size + test_size) > n:
            raise ValueError("insufficient discovery history for fixed walk-forward splits")
        folds: list[dict[str, Any]] = []
        for index in range(self.config.fold_count):
            valid = pool[start : start + val_size]
            test = pool[start + val_size : start + val_size + test_size]
            train = [trade for trade in pool[:start] if trade.closed_time < valid[0].decision_time]
            # Purge trades whose outcomes had not completed before test starts.
            valid_known = [trade for trade in valid if trade.closed_time < test[0].decision_time]
            if len(train) < self.config.minimum_train_trades:
                raise ValueError("purged training slice is too small")
            if len(valid_known) < self.config.minimum_validation_trades:
                raise ValueError("purged validation slice is too small")
            selection = self._choose(valid_known)
            folds.append(
                {
                    "fold": index + 1,
                    "train_count_purged": len(train),
                    "validation_count_purged": len(valid_known),
                    "test_count": len(test),
                    "validation_end_before_test_start": max(
                        trade.closed_time for trade in valid_known
                    ) < test[0].decision_time,
                    "train_last_close_before_validation": max(
                        trade.closed_time for trade in train
                    ) < valid[0].decision_time,
                    "selected_on_validation": selection.name,
                    "validation_metrics_by_policy": {
                        policy.name: self._metrics(valid_known, policy) for policy in self.policies
                    },
                    "test_rule_metrics": self._metrics(test, None),
                    "test_candidate_metrics": self._metrics(test, selection),
                }
            )
            start += val_size + test_size
        # Never use test or holdout outcomes to choose final policy.
        return folds, pool, holdout

    def discover(
        self,
        discovery_trades: list[dict[str, Any]],
        *,
        frozen_at: datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        prepared, provenance = self._prepare(discovery_trades)
        now = frozen_at or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("frozen_at must be timezone aware")
        now = now.astimezone(UTC)
        if prepared[-1].decision_time >= now or max(t.closed_time for t in prepared) >= now:
            raise ValueError("discovery trades must be finalized before freezing")
        folds, _pool, holdout = self._folds(prepared)
        # Explicitly reuse only the purged validation partitions, reconstructed by boundaries.
        validation_slices: list[PreparedTrade] = []
        pool = prepared[: -len(holdout)]
        n = len(pool)
        start = max(self.config.minimum_train_trades, math.floor(n * self.config.initial_train_fraction))
        val_size = max(self.config.minimum_validation_trades, math.floor(n * self.config.validation_fraction))
        test_size = max(self.config.minimum_test_trades, math.floor(n * self.config.test_fraction))
        for _ in range(self.config.fold_count):
            test_start = pool[start + val_size].decision_time
            validation_slices.extend(
                trade for trade in pool[start : start + val_size]
                if trade.closed_time < test_start
            )
            start += val_size + test_size
        selected = self._choose(validation_slices)
        holdout_rule = self._metrics(holdout, None)
        holdout_candidate = self._metrics(holdout, selected)
        discovery_digest = self._hash(discovery_trades)
        frozen_body: dict[str, Any] = {
            "schema_version": self.MANIFEST_SCHEMA_VERSION,
            "phase": "5.7.2",
            "research_only": True,
            "auto_production_promotion": False,
            "frozen_at": now.isoformat(),
            "discovery_cutoff": max(t.decision_time for t in prepared).isoformat(),
            "discovery_sha256": discovery_digest,
            "discovery_order_ids": sorted(t.order_id for t in prepared),
            "entry_feature_schema_version": "entry_feature_schema_v1",
            "study_config": asdict(self.config),
            "presets": [policy.to_dict() for policy in self.policies],
            "selected_policy": selected.to_dict(),
            "selected_policy_hash": self._hash(selected.to_dict()),
            "minimum_future_oos_timestamp_rule": "decision_timestamp_strictly_after_freeze",
            "v1_oos_reuse_allowed": False,
            "oos_retuning_allowed": False,
            "execution_mutation_allowed": False,
        }
        manifest = {**frozen_body, "manifest_hash": self._hash(frozen_body)}
        report: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.7.2",
            "research_only": True,
            "study_type": "predeclared_entry_filter_signal_level_counterfactual",
            "not_full_portfolio_replay": True,
            "source_metrics_net_of_fees_slippage": True,
            "source_provenance": provenance,
            "observed_signals": len(prepared),
            "folds": folds,
            "validation_selected_policy": selected.name,
            "validation_metrics_by_policy": {
                policy.name: self._metrics(validation_slices, policy) for policy in self.policies
            },
            "holdout": {
                "trade_count": len(holdout),
                "first_decision_at": holdout[0].decision_time.isoformat(),
                "last_decision_at": holdout[-1].decision_time.isoformat(),
                "rule_based": holdout_rule,
                "candidate_v2": holdout_candidate,
            },
            "sample_guard": {
                "holdout_has_selected_trades": holdout_candidate["trade_count"] > 0,
                "three_fold_validation_without_test_selection": True,
                "positive_holdout_expectancy": (
                    holdout_candidate["expectancy_r"] is not None
                    and holdout_candidate["expectancy_r"] > 0
                ),
            },
            "candidate_status": "FROZEN_RESEARCH_ONLY",
            "production_promotion_allowed": False,
            "future_oos_required": True,
            "selected_policy_hash": manifest["selected_policy_hash"],
            "manifest_hash": manifest["manifest_hash"],
        }
        return report, manifest

    def forward_validate(
        self,
        future_trades: list[dict[str, Any]],
        *,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        body = {name: value for name, value in manifest.items() if name != "manifest_hash"}
        if manifest.get("schema_version") != self.MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported Candidate V2 frozen manifest")
        if manifest.get("manifest_hash") != self._hash(body):
            raise ValueError("Candidate V2 frozen manifest hash mismatch")
        if manifest.get("selected_policy_hash") != self._hash(manifest.get("selected_policy")):
            raise ValueError("Candidate V2 frozen policy hash mismatch")
        if manifest.get("v1_oos_reuse_allowed") is not False:
            raise ValueError("frozen manifest must prohibit V1 OOS reuse")
        if manifest.get("oos_retuning_allowed") is not False:
            raise ValueError("frozen manifest must prohibit OOS retuning")
        if manifest.get("auto_production_promotion") is not False:
            raise ValueError("frozen manifest must prohibit auto promotion")
        frozen_at = self._time(manifest.get("frozen_at"), "frozen_at")
        cutoff = self._time(manifest.get("discovery_cutoff"), "discovery_cutoff")
        if cutoff >= frozen_at:
            raise ValueError("invalid candidate freeze chronology")
        if not future_trades:
            return {
                "schema_version": self.FORWARD_SCHEMA_VERSION,
                "phase": "5.7.3",
                "state": "AWAITING_FRESH_OOS",
                "future_signals": 0,
                "promotion_allowed": False,
                "manifest_hash": manifest["manifest_hash"],
            }
        prepared, provenance = self._prepare(future_trades)
        discovery_ids = set(manifest["discovery_order_ids"])
        if any(t.order_id in discovery_ids for t in prepared):
            raise ValueError("future OOS overlaps discovery order IDs")
        if any(t.decision_time <= frozen_at or t.decision_time <= cutoff for t in prepared):
            raise ValueError("future OOS must start strictly after Candidate V2 freeze")
        policy = EntryQualityPolicy(**manifest["selected_policy"])
        return {
            "schema_version": self.FORWARD_SCHEMA_VERSION,
            "phase": "5.7.3",
            "research_only": True,
            "state": "RESEARCH_EVIDENCE_ONLY",
            "source_provenance": provenance,
            "future_signals": len(prepared),
            "rule_based": self._metrics(prepared, None),
            "candidate_v2": self._metrics(prepared, policy),
            "candidate_name": policy.name,
            "manifest_hash": manifest["manifest_hash"],
            "promotion_allowed": False,
            "oos_retuning_performed": False,
            "production_mutation": False,
        }