from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.models import Candle
from app.research.feature_dataset import ResearchFeatureDatasetProjection


def timeframe_to_milliseconds(timeframe: str) -> int:
    if len(timeframe) < 2:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    unit = timeframe[-1]
    try:
        value = int(timeframe[:-1])
    except ValueError as exc:
        raise ValueError(f"unsupported timeframe: {timeframe}") from exc
    multipliers = {
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
    }
    if value <= 0 or unit not in multipliers:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return value * multipliers[unit]


class HistoricalDatasetDiagnostics:
    """Quality and coverage diagnostics for multi-year historical research datasets."""

    SCHEMA_VERSION = "historical_dataset_diagnostics_v1"

    @staticmethod
    def candle_continuity(candles: list[Candle], timeframe: str) -> dict[str, Any]:
        interval_ms = timeframe_to_milliseconds(timeframe)
        duplicate_timestamps = 0
        out_of_order = 0
        missing_intervals = 0
        gap_count = 0
        largest_gap_intervals = 0

        for previous, current in zip(candles, candles[1:], strict=False):
            delta = current.timestamp_ms - previous.timestamp_ms
            if delta == 0:
                duplicate_timestamps += 1
                continue
            if delta < 0:
                out_of_order += 1
                continue
            if delta > interval_ms:
                gap_intervals = max(0, delta // interval_ms - 1)
                if gap_intervals > 0:
                    gap_count += 1
                    missing_intervals += gap_intervals
                    largest_gap_intervals = max(largest_gap_intervals, gap_intervals)

        first_timestamp = candles[0].timestamp_ms if candles else None
        last_timestamp = candles[-1].timestamp_ms if candles else None
        return {
            "timeframe": timeframe,
            "interval_ms": interval_ms,
            "candle_count": len(candles),
            "first_timestamp_ms": first_timestamp,
            "last_timestamp_ms": last_timestamp,
            "duplicate_timestamps": duplicate_timestamps,
            "out_of_order_timestamps": out_of_order,
            "gap_count": gap_count,
            "missing_intervals": missing_intervals,
            "largest_gap_intervals": largest_gap_intervals,
            "status": (
                "PASS"
                if duplicate_timestamps == 0 and out_of_order == 0 and missing_intervals == 0
                else "WARN"
            ),
        }

    @staticmethod
    def trade_coverage(trades: list[dict[str, Any]]) -> dict[str, Any]:
        strategies: Counter[str] = Counter()
        regimes: Counter[str] = Counter()
        years: Counter[str] = Counter()
        sides: Counter[str] = Counter()
        order_ids: Counter[str] = Counter()

        for trade in trades:
            strategies[str(trade.get("strategy_id", "unknown"))] += 1
            regimes[str(trade.get("entry_market_regime", "unknown"))] += 1
            sides[str(trade.get("side", "unknown"))] += 1
            order_ids[str(trade.get("order_id", ""))] += 1
            opened_at = trade.get("created_at") or trade.get("opened_at")
            if opened_at:
                try:
                    year = str(datetime.fromisoformat(str(opened_at)).astimezone(UTC).year)
                except ValueError:
                    year = "invalid"
                years[year] += 1

        duplicate_order_ids = sum(count - 1 for count in order_ids.values() if count > 1)
        return {
            "sample_size": len(trades),
            "strategies": dict(sorted(strategies.items())),
            "market_regimes": dict(sorted(regimes.items())),
            "years": dict(sorted(years.items())),
            "sides": dict(sorted(sides.items())),
            "duplicate_order_ids": duplicate_order_ids,
        }

    @classmethod
    def build(
        cls,
        *,
        candles: list[Candle],
        trades: list[dict[str, Any]],
        timeframe: str,
    ) -> dict[str, Any]:
        continuity = cls.candle_continuity(candles, timeframe)
        coverage = cls.trade_coverage(trades)
        feature_quality = ResearchFeatureDatasetProjection.quality(
            [],
            historical_trades=trades,
            source="historical",
        )
        split = ResearchFeatureDatasetProjection.temporal_split(
            [],
            historical_trades=trades,
            source="historical",
        )
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "candle_continuity": continuity,
            "trade_coverage": coverage,
            "feature_quality": feature_quality,
            "temporal_split": split,
            "readiness": {
                "candles": continuity["status"],
                "dataset": feature_quality["readiness"]["dataset"],
                "training": feature_quality["readiness"]["training"],
                "split": split["readiness"],
            },
        }
