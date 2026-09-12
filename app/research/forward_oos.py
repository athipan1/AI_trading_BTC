from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.research.frozen_oos_validation import FrozenOOSValidationResearch
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import (
    HistoricalReplayConfig,
    HistoricalStrategyReplay,
    canonical_replay_strategies,
)
from app.research.historical_store import HistoricalResearchStore


@dataclass(frozen=True)
class ForwardOOSConfig:
    boundary_iso: str = "2026-09-01T00:00:00+00:00"
    warmup_hours: int = 300
    too_early_trade_count: int = 20
    intermediate_trade_count: int = 50
    stronger_evidence_trade_count: int = 100


class ForwardOOSAccumulator:
    """Phase 5.6.1 append-only OOS accumulation using the canonical replay pipeline."""

    SCHEMA_VERSION = "forward_oos_accumulation_schema_v1"

    def __init__(
        self,
        *,
        config: ForwardOOSConfig | None = None,
        validator: FrozenOOSValidationResearch | None = None,
    ) -> None:
        self.config = config or ForwardOOSConfig()
        self.validator = validator or FrozenOOSValidationResearch()

    @staticmethod
    def _iso_to_ms(value: str) -> int:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp() * 1000)

    @staticmethod
    def _ms_to_iso(value: int) -> str:
        return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()

    def evidence_stage(self, trade_count: int) -> str:
        if trade_count < self.config.too_early_trade_count:
            return "TOO_EARLY"
        if trade_count < self.config.intermediate_trade_count:
            return "EARLY_SIGNAL"
        if trade_count < self.config.stronger_evidence_trade_count:
            return "INTERMEDIATE"
        return "STRONGER_EVIDENCE"

    def accumulation_window(self, until_iso: str) -> tuple[int, int, int]:
        boundary_ms = self._iso_to_ms(self.config.boundary_iso)
        until_ms = self._iso_to_ms(until_iso)
        if until_ms <= boundary_ms:
            raise ValueError("Phase 5.6.1 --until must be after the frozen OOS boundary")
        warmup_start = datetime.fromtimestamp(boundary_ms / 1000, tz=UTC) - timedelta(
            hours=self.config.warmup_hours
        )
        return int(warmup_start.timestamp() * 1000), boundary_ms, until_ms

    def accumulate(
        self,
        *,
        discovery_trades: list[dict[str, Any]],
        manifest: dict[str, Any],
        oos_store: HistoricalResearchStore,
        market_data: HistoricalMarketDataService,
        until_iso: str,
        replay_config: HistoricalReplayConfig,
        dataset_run_id: str,
        git_commit: str | None = None,
    ) -> dict[str, Any]:
        since_ms, boundary_ms, until_ms = self.accumulation_window(until_iso)
        discovery_cutoff = self._iso_to_ms(str(manifest["discovery_cutoff"]))
        minimum_timestamp_ms = max(boundary_ms, discovery_cutoff + 1)

        candles = market_data.fetch_range(
            replay_config.symbol,
            replay_config.timeframe,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        integrity = market_data.integrity_report(
            candles,
            timeframe=replay_config.timeframe,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        if not integrity["segment_replay_safe"]:
            raise ValueError("Phase 5.6.1 market data is unsafe for segmented replay")

        segments = market_data.contiguous_segments(
            candles,
            timeframe=replay_config.timeframe,
        )
        engine = HistoricalStrategyReplay(replay_config)
        inserted = 0
        duplicate_skipped = 0
        filtered_before_boundary = 0
        replay_closed_trades = 0
        strategy_reports: list[dict[str, Any]] = []

        for strategy in canonical_replay_strategies():
            replay = engine.replay_segments(segments, strategy)
            replay_closed_trades += int(replay["closed_trades"])
            append = oos_store.append_immutable_replay(
                replay,
                dataset_run_id=dataset_run_id,
                minimum_entry_feature_timestamp_ms=minimum_timestamp_ms,
                git_commit=git_commit,
            )
            inserted += int(append["inserted"])
            duplicate_skipped += int(append["duplicate_skipped"])
            filtered_before_boundary += int(append["filtered_before_boundary"])
            strategy_reports.append(
                {
                    "strategy_id": strategy.strategy_id,
                    "closed_trades": int(replay["closed_trades"]),
                    "inserted": int(append["inserted"]),
                    "duplicate_skipped": int(append["duplicate_skipped"]),
                    "filtered_before_boundary": int(append["filtered_before_boundary"]),
                }
            )

        oos_trades = oos_store.load()
        validation = self.validator.validate(
            discovery_trades,
            oos_trades,
            manifest=manifest,
        )
        trade_count = len(oos_trades)

        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.6.1",
            "research_only": True,
            "production_position_store_mutated": False,
            "method": "append_only_fresh_oos_accumulation_and_forward_validation",
            "optimization_performed": False,
            "oos_retuning_performed": False,
            "config": asdict(self.config),
            "frozen_contract": {
                "manifest_hash": manifest.get("manifest_hash"),
                "policy_hash": manifest.get("policy_hash"),
                "model_fingerprint": manifest.get("model_fingerprint"),
                "discovery_cutoff": manifest.get("discovery_cutoff"),
                "boundary_iso": self.config.boundary_iso,
            },
            "market_data": {
                "warmup_since": self._ms_to_iso(since_ms),
                "fresh_boundary": self._ms_to_iso(boundary_ms),
                "until": self._ms_to_iso(until_ms),
                "candles": len(candles),
                "missing_intervals": int(integrity["missing_interval_count"]),
                "segments": len(segments),
                "synthetic_candles": 0,
            },
            "accumulation": {
                "replay_closed_trades": replay_closed_trades,
                "new_trades_added": inserted,
                "duplicate_trades_skipped": duplicate_skipped,
                "filtered_before_boundary": filtered_before_boundary,
                "oos_trade_count": trade_count,
                "evidence_stage": self.evidence_stage(trade_count),
                "strategy_reports": strategy_reports,
            },
            "phase56_validation": validation,
            "validation_status": validation["validation_status"],
            "superiority_status": validation["superiority_status"],
        }
