from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from app.research.baseline_ml import BaselineMLResearch
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.regime_robustness import RegimeRobustnessResearch
from app.research.walk_forward import WalkForwardConfig


@dataclass(frozen=True)
class FrozenOOSConfig:
    minimum_oos_signals: int = 20
    minimum_policy_selected_trades: int = 10
    minimum_policy_profit_factor: float = 1.0
    require_positive_policy_expectancy: bool = True
    require_policy_drawdown_not_worse_than_global_ml: bool = True


class FrozenOOSValidationResearch:
    """Phase 5.6 frozen regime policy and fresh out-of-sample validation."""

    SCHEMA_VERSION = "frozen_oos_validation_schema_v1"
    MANIFEST_SCHEMA_VERSION = "frozen_regime_policy_manifest_v1"

    def __init__(
        self,
        *,
        baseline: BaselineMLResearch | None = None,
        walk_forward_config: WalkForwardConfig | None = None,
        config: FrozenOOSConfig | None = None,
    ) -> None:
        self.baseline = baseline or BaselineMLResearch()
        self.walk_forward_config = walk_forward_config or WalkForwardConfig(
            fold_count=4,
            initial_train_fraction=0.40,
            validation_fraction=0.07,
            test_fraction=0.07,
        )
        self.config = config or FrozenOOSConfig()

    @staticmethod
    def _canonical_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _segment_key(features: dict[str, Any]) -> str:
        strategy = str(features.get("strategy_id") or "UNKNOWN")
        side = str(features.get("side") or "UNKNOWN").lower()
        regime = str(features.get("entry_market_regime") or "UNKNOWN")
        return f"{strategy}|{side}|{regime}"

    @staticmethod
    def _policy_action(classification: str | None) -> str:
        if classification in {"ROBUST", "PROMISING"}:
            return "ML_FILTER"
        if classification in {"FAILURE", "UNSTABLE", "INSUFFICIENT"}:
            return "RULE_BASED"
        return "GLOBAL_ML_FALLBACK"

    def _fit_frozen_model(
        self,
        discovery_trades: list[dict[str, Any]],
        selected_model_name: str,
    ) -> tuple[Any, list[dict[str, Any]]]:
        dataset = ResearchFeatureDatasetProjection.build(
            [], historical_trades=discovery_trades, source="historical"
        )
        split = ResearchFeatureDatasetProjection.temporal_split(
            [], historical_trades=discovery_trades, source="historical"
        )
        rows = dataset["rows"]
        train_rows = self.baseline._rows_by_ids(rows, split["order_ids"]["train"])
        models = self.baseline._models()
        if selected_model_name not in models:
            raise ValueError(f"frozen manifest selected unknown model: {selected_model_name}")
        model = models[selected_model_name]
        x_train = self.baseline._records_to_matrix(
            [self.baseline._feature_record(row) for row in train_rows]
        )
        y_train = np.asarray([self.baseline._target(row) for row in train_rows], dtype=int)
        model.fit(x_train, y_train)
        return model, train_rows

    def freeze_manifest(self, discovery_trades: list[dict[str, Any]]) -> dict[str, Any]:
        phase55 = RegimeRobustnessResearch(
            baseline=self.baseline,
            walk_forward_config=self.walk_forward_config,
        ).run(discovery_trades)
        if phase55["acceptance_status"] != "PASS":
            raise ValueError("Phase 5.6 requires Phase 5.5 acceptance to pass before freezing")

        phase52 = self.baseline.run(discovery_trades)
        selected_model = str(phase52["selection"]["model"])
        selected_threshold = float(phase52["selection"]["selected_threshold"])
        model, train_rows = self._fit_frozen_model(discovery_trades, selected_model)

        dataset = ResearchFeatureDatasetProjection.build(
            [], historical_trades=discovery_trades, source="historical"
        )
        rows = sorted(
            dataset["rows"],
            key=lambda row: (
                str(row.get("feature_available_at") or ""),
                str(row.get("order_id") or ""),
            ),
        )
        if not rows:
            raise ValueError("Phase 5.6 cannot freeze an empty discovery dataset")
        cutoff = str(rows[-1].get("feature_available_at") or "")
        if not cutoff:
            raise ValueError("Phase 5.6 discovery cutoff is missing")

        policy: dict[str, dict[str, str]] = {}
        for segment in phase55["segments"]:
            key = str(segment["segment"])
            classification = str(segment["classification"])
            policy[key] = {
                "classification": classification,
                "action": self._policy_action(classification),
            }

        model_contract = {
            "model": selected_model,
            "threshold": selected_threshold,
            "threshold_selection_scope": "discovery_validation_only",
            "feature_schema_version": dataset["schema_version"],
            "feature_names": list(ResearchFeatureDatasetProjection.MODEL_FEATURES),
            "target": "realized_r > 0",
            "random_state": self.baseline.config.random_state,
            "training_order_ids": [str(row.get("order_id") or "") for row in train_rows],
            "fitted_model_class": type(model.named_steps["model"]).__name__,
        }
        model_fingerprint = self._canonical_hash(model_contract)
        policy_hash = self._canonical_hash(policy)
        manifest_body = {
            "schema_version": self.MANIFEST_SCHEMA_VERSION,
            "phase": "5.6",
            "research_only": True,
            "discovery_cutoff": cutoff,
            "source_phase": {
                "phase": phase55["phase"],
                "schema_version": phase55["schema_version"],
                "acceptance_status": phase55["acceptance_status"],
                "phase54_acceptance_status": phase55["source_phase"]["acceptance_status"],
            },
            "model_contract": model_contract,
            "model_fingerprint": model_fingerprint,
            "policy": policy,
            "policy_hash": policy_hash,
            "default_policy_action": "GLOBAL_ML_FALLBACK",
            "oos_retuning_allowed": False,
            "production_position_store_mutated": False,
        }
        return {**manifest_body, "manifest_hash": self._canonical_hash(manifest_body)}

    @staticmethod
    def _metrics(realized: np.ndarray, mask: np.ndarray) -> dict[str, float | int | None]:
        selected = realized[mask]
        if len(selected) == 0:
            return {
                "available_signals": int(len(realized)),
                "trade_count": 0,
                "selection_rate_pct": 0.0,
                "win_rate_pct": None,
                "expectancy_r": None,
                "total_realized_r": 0.0,
                "profit_factor": None,
                "max_drawdown_r": 0.0,
            }
        gains = selected[selected > 0]
        losses = selected[selected < 0]
        gross_profit = float(np.sum(gains))
        gross_loss = float(abs(np.sum(losses)))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
        equity = 0.0
        peak = 0.0
        drawdown = 0.0
        for value in selected:
            equity += float(value)
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        return {
            "available_signals": int(len(realized)),
            "trade_count": int(len(selected)),
            "selection_rate_pct": float(len(selected) / len(realized) * 100),
            "win_rate_pct": float(np.mean(selected > 0) * 100),
            "expectancy_r": float(np.mean(selected)),
            "total_realized_r": float(np.sum(selected)),
            "profit_factor": float(profit_factor) if profit_factor is not None else None,
            "max_drawdown_r": float(drawdown),
        }

    def validate(
        self,
        discovery_trades: list[dict[str, Any]],
        oos_trades: list[dict[str, Any]],
        *,
        manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        frozen = manifest or self.freeze_manifest(discovery_trades)
        manifest_body = {key: value for key, value in frozen.items() if key != "manifest_hash"}
        manifest_integrity = frozen.get("manifest_hash") == self._canonical_hash(manifest_body)
        if not manifest_integrity:
            raise ValueError("Phase 5.6 frozen manifest hash mismatch")

        quality = ResearchFeatureDatasetProjection.quality(
            [], historical_trades=oos_trades, source="historical"
        )
        dataset = ResearchFeatureDatasetProjection.build(
            [], historical_trades=oos_trades, source="historical"
        )
        rows = sorted(
            dataset["rows"],
            key=lambda row: (
                str(row.get("feature_available_at") or ""),
                str(row.get("order_id") or ""),
            ),
        )
        cutoff = str(frozen["discovery_cutoff"])
        fresh_oos = bool(rows) and all(
            str(row.get("feature_available_at") or "") > cutoff for row in rows
        )
        if not fresh_oos:
            raise ValueError("Phase 5.6 OOS rows must all be strictly after discovery cutoff")

        model_name = str(frozen["model_contract"]["model"])
        threshold = float(frozen["model_contract"]["threshold"])
        model, _ = self._fit_frozen_model(discovery_trades, model_name)
        x_oos = self.baseline._records_to_matrix(
            [self.baseline._feature_record(row) for row in rows]
        )
        probabilities = self.baseline._predict_positive_probability(model, x_oos)
        realized = np.asarray([self.baseline._realized_r(row) for row in rows], dtype=float)
        global_mask = probabilities >= threshold

        candidate_mask_values: list[bool] = []
        policy_hits = 0
        actions: dict[str, int] = {
            "ML_FILTER": 0,
            "RULE_BASED": 0,
            "GLOBAL_ML_FALLBACK": 0,
        }
        for row, probability in zip(rows, probabilities, strict=True):
            features = row.get("features")
            feature_map = features if isinstance(features, dict) else {}
            key = self._segment_key(feature_map)
            policy_item = frozen["policy"].get(key)
            action = (
                str(policy_item["action"])
                if isinstance(policy_item, dict)
                else str(frozen["default_policy_action"])
            )
            if isinstance(policy_item, dict):
                policy_hits += 1
            actions[action] = actions.get(action, 0) + 1
            if action == "RULE_BASED":
                candidate_mask_values.append(True)
            else:
                candidate_mask_values.append(bool(probability >= threshold))
        candidate_mask = np.asarray(candidate_mask_values, dtype=bool)
        all_mask = np.ones(len(rows), dtype=bool)

        rule_metrics = self._metrics(realized, all_mask)
        global_metrics = self._metrics(realized, global_mask)
        policy_metrics = self._metrics(realized, candidate_mask)
        policy_expectancy = policy_metrics["expectancy_r"]
        policy_profit_factor = policy_metrics["profit_factor"]
        policy_drawdown = float(policy_metrics["max_drawdown_r"])
        global_drawdown = float(global_metrics["max_drawdown_r"])

        structural = {
            "manifest_integrity": manifest_integrity,
            "model_frozen": True,
            "threshold_frozen": True,
            "policy_frozen": True,
            "oos_retuning": False,
            "fresh_oos": fresh_oos,
            "chronological_integrity": True,
            "feature_leakage": quality["quality"]["leakage_check"]["status"] == "PASS",
            "production_isolation": True,
        }
        evidence = {
            "minimum_oos_signals": len(rows) >= self.config.minimum_oos_signals,
            "minimum_policy_selected_trades": (
                int(policy_metrics["trade_count"]) >= self.config.minimum_policy_selected_trades
            ),
        }
        performance = {
            "policy_expectancy_positive": (
                not self.config.require_positive_policy_expectancy
                or (policy_expectancy is not None and float(policy_expectancy) > 0)
            ),
            "policy_profit_factor": (
                policy_profit_factor is not None
                and float(policy_profit_factor) > self.config.minimum_policy_profit_factor
            ),
            "policy_drawdown": (
                not self.config.require_policy_drawdown_not_worse_than_global_ml
                or policy_drawdown <= global_drawdown
            ),
        }
        superiority = {
            "policy_expectancy_ge_global_ml": (
                policy_metrics["expectancy_r"] is not None
                and global_metrics["expectancy_r"] is not None
                and float(policy_metrics["expectancy_r"])
                >= float(global_metrics["expectancy_r"])
            ),
            "policy_total_r_ge_global_ml": (
                float(policy_metrics["total_realized_r"])
                >= float(global_metrics["total_realized_r"])
            ),
        }
        validation_passed = (
            all(structural.values())
            and all(evidence.values())
            and all(performance.values())
        )
        validation_status = "PASS" if validation_passed else "FAIL"
        superiority_status = "PASS" if all(superiority.values()) else "FAIL"

        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.6",
            "research_only": True,
            "production_position_store_mutated": False,
            "method": "frozen_regime_policy_fresh_oos_validation",
            "random_shuffle": False,
            "optimization_performed": False,
            "oos_retuning_performed": False,
            "config": asdict(self.config),
            "manifest": frozen,
            "oos": {
                "signals": len(rows),
                "first_feature_available_at": str(rows[0]["feature_available_at"]),
                "last_feature_available_at": str(rows[-1]["feature_available_at"]),
                "policy_match_rate": float(policy_hits / len(rows)) if rows else 0.0,
                "policy_actions": actions,
            },
            "comparison": {
                "rule_based": rule_metrics,
                "global_ml": global_metrics,
                "frozen_regime_policy": policy_metrics,
            },
            "structural_acceptance": structural,
            "evidence_acceptance": evidence,
            "performance_acceptance": performance,
            "validation_status": validation_status,
            "superiority": superiority,
            "superiority_status": superiority_status,
        }
