"""Phase 5.7.3 append-only, post-freeze Candidate V2 research accumulator.

This module cannot access trading execution, mutate V1 OOS, or promote a policy.
It replays the canonical strategies and their frozen V2 wrappers independently.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.research.candidate_v2 import CandidateV2ReplayStrategy, EntryQualityPolicy
from app.research.candidate_v2_research import CandidateV2Research
from app.research.historical_market_data import HistoricalMarketDataService
from app.research.historical_replay import (
    HistoricalReplayConfig,
    HistoricalStrategyReplay,
    canonical_replay_strategies,
)
from app.research.historical_store import HistoricalResearchStore
from app.research.realized_r_metrics import realized_r_selection_metrics


@dataclass(frozen=True)
class CandidateV2ForwardConfig:
    """Pinned replay cost and warmup settings, not tunable from OOS outcomes."""

    warmup_hours: int = 300
    quantity: float = 0.001
    fee_rate: float = 0.001
    slippage_bps: float = 2.0
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"


class CandidateV2ForwardAccumulator:
    SCHEMA_VERSION = "candidate_v2_forward_accumulation_v1"
    CHECKPOINT_SCHEMA_VERSION = "candidate_v2_forward_checkpoint_v1"
    HOUR_MS = 3_600_000

    def __init__(
        self,
        *,
        config: CandidateV2ForwardConfig | None = None,
        researcher: CandidateV2Research | None = None,
    ) -> None:
        self.config = config or CandidateV2ForwardConfig()
        self.researcher = researcher or CandidateV2Research()
        if self.config.symbol != "BTC/USDT" or self.config.timeframe != "1h":
            raise ValueError("Phase 5.7.3 is pinned to BTC/USDT 1h")
        if self.config.warmup_hours < 300:
            raise ValueError("warmup must include at least 300 pre-freeze H1 candles")
        if not (0 < self.config.quantity <= 1.0):
            raise ValueError("invalid research-only replay quantity")
        if not (0 < self.config.fee_rate <= 0.02):
            raise ValueError("fee_rate must be in (0, 0.02]")
        if not (0 < self.config.slippage_bps <= 100):
            raise ValueError("slippage_bps must be in (0, 100]")

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _parse_time(value: Any, label: str) -> datetime:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} missing")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label} is not ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{label} must be timezone-aware")
        return parsed.astimezone(UTC)

    @staticmethod
    def latest_closed_hour(now: datetime | None = None) -> datetime:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone aware")
        return current.astimezone(UTC).replace(minute=0, second=0, microsecond=0)

    def _until(self, requested: str | None, now: datetime | None) -> datetime:
        latest = self.latest_closed_hour(now)
        until = self._parse_time(requested, "until") if requested else latest
        if until != until.replace(minute=0, second=0, microsecond=0):
            raise ValueError("--until must align to UTC H1")
        if until > latest:
            raise ValueError("--until cannot include an unfinished H1 candle")
        return until

    def _pin(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "manifest_hash": manifest["manifest_hash"],
            "selected_policy_hash": manifest["selected_policy_hash"],
            "frozen_at": manifest["frozen_at"],
            "replay": asdict(self.config),
        }

    def _preflight_manifest(self, manifest: dict[str, Any]) -> tuple[EntryQualityPolicy, datetime]:
        # The existing Phase 5.7.2 gate checks both hashes and refuses retuning.
        self.researcher.forward_validate([], manifest=manifest)
        frozen = self._parse_time(manifest["frozen_at"], "frozen_at")
        policy = EntryQualityPolicy(**manifest["selected_policy"])
        return policy, frozen

    @classmethod
    def _checkpoint(cls, path: Path, expected_pin: dict[str, Any]) -> dict[str, Any] | None:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != cls.CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("invalid Phase 5.7.3 checkpoint schema")
        if payload.get("frozen_pin") != expected_pin:
            raise ValueError("checkpoint frozen policy or replay costs differ from manifest")
        if isinstance(payload.get("run_count"), bool) or not isinstance(payload.get("run_count"), int):
            raise ValueError("invalid checkpoint run count")
        if payload["run_count"] < 1:
            raise ValueError("invalid checkpoint run count")
        return payload

    @staticmethod
    def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @classmethod
    def _check_store(
        cls,
        trades: list[dict[str, Any]],
        *,
        prefix: str,
        frozen: datetime,
        expected_run_id: str | None = None,
    ) -> None:
        seen: set[str] = set()
        for trade in trades:
            order_id = str(trade.get("order_id") or "")
            if not order_id.startswith("hist-" + prefix) or order_id in seen:
                raise ValueError("OOS store contains foreign/duplicate trade IDs: refusing V1 mixing")
            seen.add(order_id)
            if trade.get("status") != "CLOSED":
                raise ValueError("future OOS store must contain closed trades only")
            decision = cls._parse_time(trade.get("decision_at"), "decision_at")
            closed = cls._parse_time(trade.get("closed_at"), "closed_at")
            if decision <= frozen or closed <= decision:
                raise ValueError("future OOS store contains pre-freeze/inconsistent trade")
            realized = trade.get("realized_r")
            if realized is None or isinstance(realized, bool):
                raise ValueError("missing realized-R value in OOS store")
            try:
                if not math.isfinite(float(realized)):
                    raise ValueError("non-finite realized-R")
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid realized-R value in OOS store") from exc
            if expected_run_id is not None and (
                trade.get("dataset_run_id") != expected_run_id
                or trade.get("source") != "binance_public_spot_ohlcv"
                or trade.get("replay_schema_version") != HistoricalStrategyReplay.SCHEMA_VERSION
            ):
                raise ValueError("OOS store source lineage differs from frozen V2 manifest")

    @classmethod
    def _preview_append(
        cls,
        existing: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
        *,
        frozen: datetime,
    ) -> None:
        """Reject source revisions BEFORE writing either of two evidence stores."""
        known = {str(item["order_id"]): item for item in existing}
        seen: dict[str, dict[str, Any]] = {}
        for trade in incoming:
            if cls._parse_time(trade["decision_at"], "decision_at") <= frozen:
                continue
            key = str(trade["order_id"])
            core = HistoricalResearchStore._core_trade(trade)
            if key in seen and seen[key] != core:
                raise ValueError("conflicting duplicate replay trade")
            seen[key] = core
            previous = known.get(key)
            if previous is not None and HistoricalResearchStore._core_trade(previous) != core:
                raise ValueError(f"immutable OOS replay conflict for order_id={key}")

    @staticmethod
    def _metrics(trades: list[dict[str, Any]]) -> dict[str, float | int | None]:
        ordered = sorted(trades, key=lambda t: (str(t["decision_at"]), str(t["order_id"])))
        realized = [float(trade["realized_r"]) for trade in ordered]
        return realized_r_selection_metrics(realized, [True] * len(realized))

    def run(
        self,
        *,
        manifest: dict[str, Any],
        market_data: HistoricalMarketDataService,
        candidate_store_path: str | Path,
        baseline_store_path: str | Path,
        checkpoint_path: str | Path,
        requested_until: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        policy, frozen = self._preflight_manifest(manifest)
        candidate_path, baseline_path, checkpoint_file = map(
            Path, (candidate_store_path, baseline_store_path, checkpoint_path)
        )
        if len({p.resolve() for p in (candidate_path, baseline_path, checkpoint_file)}) != 3:
            raise ValueError("candidate, baseline and checkpoint artifacts must be separate")
        if any(
            not path.name.startswith("phase573_v2_") or path.suffix != ".json"
            for path in (candidate_path, baseline_path, checkpoint_file)
        ):
            raise ValueError("Phase 5.7.3 evidence paths must be dedicated phase573_v2_*.json files")
        run_id = f"phase573-v2-{manifest['manifest_hash'][:16]}"
        pin = self._pin(manifest)
        checkpoint = self._checkpoint(checkpoint_file, pin)
        candidate_store = HistoricalResearchStore(candidate_path)
        baseline_store = HistoricalResearchStore(baseline_path)
        candidate_existing = candidate_store.load()
        baseline_existing = baseline_store.load()
        self._check_store(
            candidate_existing, prefix="candidate_v2_", frozen=frozen, expected_run_id=run_id
        )
        self._check_store(
            baseline_existing, prefix="triple_ema", frozen=frozen, expected_run_id=run_id
        )
        if checkpoint is not None:
            if len(candidate_existing) != checkpoint.get("candidate_trade_count") or (
                len(baseline_existing) != checkpoint.get("baseline_trade_count")
            ):
                raise ValueError("checkpoint/store divergence; manual integrity review required")
            if self._hash(candidate_existing) != checkpoint.get("candidate_store_hash") or (
                self._hash(baseline_existing) != checkpoint.get("baseline_store_hash")
            ):
                raise ValueError("checkpoint/store tampering detected")
        until = self._until(requested_until, now)
        last = (
            self._parse_time(checkpoint["last_processed_until"], "last_processed_until")
            if checkpoint is not None else None
        )
        # The candle whose open is after the freeze must itself CLOSE, then a
        # subsequent candle must open before replay may realize a fill.
        first_fresh_open_ms = (
            int(frozen.timestamp() * 1000) // self.HOUR_MS + 1
        ) * self.HOUR_MS
        too_soon = int(until.timestamp() * 1000) <= first_fresh_open_ms + self.HOUR_MS
        no_new = last is not None and until <= last
        if too_soon or no_new:
            state = "AWAITING_CLOSED_H1" if too_soon else "NO_NEW_CANDLES"
            return self._report(
                state=state,
                manifest=manifest,
                pin=pin,
                until=until,
                checkpoint=checkpoint,
                candidate=candidate_existing,
                baseline=baseline_existing,
                replay_info=None,
            )
        boundary = frozen.replace(minute=0, second=0, microsecond=0)
        since = boundary - timedelta(hours=self.config.warmup_hours)
        since_ms, until_ms = int(since.timestamp() * 1000), int(until.timestamp() * 1000)
        candles = market_data.fetch_range(
            self.config.symbol,
            self.config.timeframe,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        integrity = market_data.integrity_report(
            candles,
            timeframe=self.config.timeframe,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        if not integrity["complete_range"]:
            raise ValueError("incomplete/gapped public OHLCV; OOS state not advanced")
        segments = market_data.contiguous_segments(candles, timeframe=self.config.timeframe)
        engine = HistoricalStrategyReplay(
            HistoricalReplayConfig(
                symbol=self.config.symbol,
                timeframe=self.config.timeframe,
                quantity=self.config.quantity,
                fee_rate=self.config.fee_rate,
                slippage_bps=self.config.slippage_bps,
            )
        )
        candidate_replays: list[dict[str, Any]] = []
        baseline_replays: list[dict[str, Any]] = []
        for base in canonical_replay_strategies():
            baseline_replays.append(engine.replay_segments(segments, base))
            candidate_replays.append(
                engine.replay_segments(segments, CandidateV2ReplayStrategy(base, policy))
            )

        def fresh(replays: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                trade
                for replay in replays
                for trade in replay["trades"]
                if self._parse_time(trade["decision_at"], "decision_at") > frozen
            ]

        candidate_new = fresh(candidate_replays)
        baseline_new = fresh(baseline_replays)
        for trade in [*candidate_new, *baseline_new]:
            if self._parse_time(trade["closed_at"], "closed_at") > until:
                raise ValueError("replayed closed trade extends beyond fully closed H1 range")
        # Check the original immutable Phase 5.7.2 manifest against all new V2
        # source trades *before* appending anything. No retraining or selection.
        combined = {item["order_id"]: item for item in candidate_existing}
        # Phase 5.7.2 requires canonical historical_replay origin; the store
        # stamps this only after append. Preview canonical metadata before writing.
        combined.update(
            {item["order_id"]: {**item, "data_origin": "historical_replay"} for item in candidate_new}
        )
        validation = self.researcher.forward_validate(list(combined.values()), manifest=manifest)
        self._check_store(candidate_new, prefix="candidate_v2_", frozen=frozen)
        self._check_store(baseline_new, prefix="triple_ema", frozen=frozen)
        self._preview_append(candidate_existing, candidate_new, frozen=frozen)
        self._preview_append(baseline_existing, baseline_new, frozen=frozen)

        # Use exactly the existing append-only HistoricalResearchStore contract;
        # all pre-freeze trades have already been discarded, including late exits.
        minimum_ms = int(frozen.timestamp() * 1000) + 1
        candidate_add = candidate_store.append_immutable_replay(
            {"schema_version": HistoricalStrategyReplay.SCHEMA_VERSION, "trades": candidate_new},
            dataset_run_id=run_id,
            minimum_entry_feature_timestamp_ms=minimum_ms,
            source="binance_public_spot_ohlcv",
        )
        baseline_add = baseline_store.append_immutable_replay(
            {"schema_version": HistoricalStrategyReplay.SCHEMA_VERSION, "trades": baseline_new},
            dataset_run_id=run_id,
            minimum_entry_feature_timestamp_ms=minimum_ms,
            source="binance_public_spot_ohlcv",
        )
        candidate_all = candidate_store.load()
        baseline_all = baseline_store.load()
        updated = {
            "schema_version": self.CHECKPOINT_SCHEMA_VERSION,
            "phase": "5.7.3",
            "frozen_pin": pin,
            "last_processed_until": until.isoformat(),
            "run_count": (checkpoint["run_count"] if checkpoint else 0) + 1,
            "candidate_trade_count": len(candidate_all),
            "baseline_trade_count": len(baseline_all),
            "candidate_store_hash": self._hash(candidate_all),
            "baseline_store_hash": self._hash(baseline_all),
        }
        self._write_checkpoint(checkpoint_file, updated)
        return self._report(
            state="ACCUMULATING" if candidate_all else "AWAITING_CLOSED_V2_TRADES",
            manifest=manifest,
            pin=pin,
            until=until,
            checkpoint=updated,
            candidate=candidate_all,
            baseline=baseline_all,
            replay_info={
                "source": "binance_spot_public_market_data_only",
                "candles": len(candles),
                "from": since.isoformat(),
                "until_exclusive": until.isoformat(),
                "gaps": integrity["missing_interval_count"],
                "segments": len(segments),
                "candidate_new_trades": candidate_add["inserted"],
                "baseline_new_trades": baseline_add["inserted"],
                "synthetic_candles": 0,
            },
            validation=validation,
        )

    def _report(
        self,
        *,
        state: str,
        manifest: dict[str, Any],
        pin: dict[str, Any],
        until: datetime,
        checkpoint: dict[str, Any] | None,
        candidate: list[dict[str, Any]],
        baseline: list[dict[str, Any]],
        replay_info: dict[str, Any] | None,
        validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if validation is None:
            validation = self.researcher.forward_validate(candidate, manifest=manifest)
        return {
            "schema_version": self.SCHEMA_VERSION,
            "phase": "5.7.3",
            "research_only": True,
            "production_mutation": False,
            "trade_execution": False,
            "oos_retuning_performed": False,
            "auto_production_promotion": False,
            "promotion_allowed": False,
            "state": state,
            "frozen_pin": pin,
            "requested_until": until.isoformat(),
            "checkpoint": {
                "run_count": checkpoint["run_count"] if checkpoint else 0,
                "last_processed_until": checkpoint["last_processed_until"] if checkpoint else None,
            },
            "counts": {
                "candidate_v2_closed": len(candidate),
                "canonical_rule_based_closed": len(baseline),
            },
            "comparison": {
                "candidate_v2_full_replay": self._metrics(candidate),
                "canonical_rule_based_full_replay": self._metrics(baseline),
            },
            "forward_validation": validation,
            "market_data": replay_info,
            "basis": "independent_full_replay_next_candle_fill_with_fees_slippage",
            "not_v1_frozen_policy_promotion": True,
        }