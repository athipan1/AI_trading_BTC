"""Independent Phase 5.7.5 discovery-only execution stress comparison."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from app.models import Candle
from app.research.candidate_v2 import CandidateV2ReplayStrategy, EntryQualityPolicy
from app.research.candidate_v2_research import CandidateV2Research
from app.research.execution_realism import ExecutionRealismConfig, ExecutionRealismReplay
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import (
    HistoricalReplayConfig,
    HistoricalStrategyReplay,
    canonical_replay_strategies,
)
from app.research.realized_r_metrics import realized_r_selection_metrics


class ExecutionRealismStudy:
    SCHEMA_VERSION = "phase575_execution_realism_study_v1"

    @staticmethod
    def _time(value: str) -> datetime:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ValueError("manifest discovery cutoff must be ISO8601") from exc
        if result.tzinfo is None:
            raise ValueError("manifest discovery cutoff must include timezone")
        return result.astimezone(UTC)

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()

    @staticmethod
    def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
        ordered = sorted(trades, key=lambda t: (str(t["closed_at"]), str(t["order_id"])))
        realized = [float(trade["realized_r"]) for trade in ordered]
        return realized_r_selection_metrics(realized, [True] * len(realized))

    def run(
        self,
        *,
        candles: list[Candle],
        manifest: dict[str, Any],
        config: ExecutionRealismConfig,
        since_ms: int,
        until_ms: int,
        gap_policy: str = "reject",
        source: str = "binance_public_spot_h1",
    ) -> dict[str, Any]:
        if gap_policy not in {"reject", "segment"}:
            raise ValueError("gap-policy must be reject or segment")
        if not isinstance(manifest, dict):
            raise ValueError("frozen manifest must be an object")
        # Preserve the frozen policy contract; this does not train or promote anything.
        CandidateV2Research().forward_validate([], manifest=manifest)
        cutoff_ms = int(self._time(manifest["discovery_cutoff"]).timestamp() * 1000)
        frozen_ms = int(self._time(manifest["frozen_at"]).timestamp() * 1000)
        if until_ms > cutoff_ms or since_ms >= cutoff_ms or until_ms >= frozen_ms:
            raise ValueError("Phase 5.7.5 cannot consume post-discovery/OOS candles")
        if until_ms <= since_ms:
            raise ValueError("until must be later than since")
        if until_ms % ExecutionRealismReplay.HOUR_MS or since_ms % ExecutionRealismReplay.HOUR_MS:
            raise ValueError("study range must use closed UTC H1 boundaries")
        if not candles or len(candles) > 5000:
            raise ValueError("study requires 1..5000 historical H1 candles per run")
        integrity = HistoricalMarketDataService.integrity_report(
            candles, timeframe="1h", since_ms=since_ms, until_ms=until_ms
        )
        if not integrity["segment_replay_safe"]:
            raise ValueError("missing range endpoints or invalid candle ordering")
        if gap_policy == "reject" and not integrity["complete_range"]:
            raise ValueError("OHLCV gaps forbidden: use --gap-policy segment explicitly")
        segments = HistoricalMarketDataService.contiguous_segments(candles, timeframe="1h")
        old = HistoricalStrategyReplay(HistoricalReplayConfig(
            symbol=config.symbol,
            timeframe=config.timeframe,
            quantity=config.quantity,
            fee_rate=config.fee_rate,
            slippage_bps=config.slippage_bps,
        ))
        newer = ExecutionRealismReplay(config)
        policy = EntryQualityPolicy(**manifest["selected_policy"])
        comparisons: dict[str, Any] = {}
        for base in canonical_replay_strategies():
            for strategy in (base, CandidateV2ReplayStrategy(base, policy)):
                legacy = old.replay_segments(segments, strategy)
                realistic = newer.replay_segments(segments, strategy)
                comparisons[strategy.strategy_id] = {
                    "legacy": self._metrics(legacy["trades"]),
                    "realism": self._metrics(realistic["trades"]),
                    "ambiguous_sl_tp_bars": realistic["ambiguous_sl_tp_bars"],
                    "stop_gap_exits": realistic["stop_gap_exits"],
                    "rejected_unsafe_entries": realistic["rejected_unsafe_entries"],
                    "legacy_closed": legacy["closed_trades"],
                    "realism_closed": realistic["closed_trades"],
                }
        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.7.5",
            "research_only": True,
            "trade_execution": False,
            "production_mutation": False,
            "promotion_allowed": False,
            "oos_retuning_performed": False,
            "freeze_unchanged": True,
            "data_scope": "HISTORICAL_DISCOVERY_ONLY_NOT_FRESH_OOS",
            "manifest_hash": manifest["manifest_hash"],
            "policy_hash": manifest["selected_policy_hash"],
            "selected_policy_name": policy.name,
            "discovery_cutoff": manifest["discovery_cutoff"],
            "source": source,
            "source_ohlcv_sha256": self._hash([
                [c.timestamp_ms, c.open, c.high, c.low, c.close, c.volume] for c in candles
            ]),
            "since_utc": datetime.fromtimestamp(since_ms / 1000, tz=UTC).isoformat(),
            "until_exclusive_utc": datetime.fromtimestamp(until_ms / 1000, tz=UTC).isoformat(),
            "ohlcv_integrity": {k: integrity[k] for k in (
                "expected_candles", "actual_candles", "missing_interval_count",
                "complete_range", "segment_replay_safe"
            )},
            "execution_assumptions": asdict(config),
            "intrabar_policy": "SL_FIRST_IF_SL_AND_TP_TOUCH_SAME_H1",
            "limits": [
                "H1 bar path order unknown; stop first when both levels touch",
                "Long fixed initial SL is a stress assumption, not the deployed EMA50-only exit",
                "Stop/target triggers model market fills, no order-book liquidity or partial fills",
                "Synthetic flat 8h funding sensitivity, not actual timestamped exchange funding",
                "No mark-to-market portfolio equity curve or liquidation modeling",
                "Only closed replay trades contribute to realized-R metrics",
            ],
            "comparisons": comparisons,
        }