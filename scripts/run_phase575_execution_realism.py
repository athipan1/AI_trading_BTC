"""Phase 5.7.5 standalone research-only historical execution stress CLI.

This script reads public Binance Spot H1 or explicitly supplied OHLCV JSON.
It never reads/modifies Phase 5.7.3 evidence stores or submits orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import Candle
from app.research.binance_public_ohlcv import BinancePublicOHLCV
from app.research.execution_realism import ExecutionRealismConfig
from app.research.execution_realism_study import ExecutionRealismStudy

HOUR_MS = 3_600_000


def _parse_hour(value: str) -> int:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid UTC date/time: {value}") from exc
    if dt.tzinfo is None:
        # Bare dates, e.g. 2026-06-01, are explicitly UTC.
        if "T" in value or " " in value:
            raise ValueError("timestamps with time require explicit timezone")
        dt = dt.replace(tzinfo=UTC)
    ms = int(dt.astimezone(UTC).timestamp() * 1000)
    if ms < 0 or ms % HOUR_MS:
        raise ValueError("range must align with UTC H1 open")
    return ms


def _load_candles(path: Path) -> list[Candle]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != "phase575_ohlcv_v1":
        raise ValueError("offline input must use phase575_ohlcv_v1 (not a research trade store)")
    if raw.get("symbol") != "BTC/USDT" or raw.get("timeframe") != "1h":
        raise ValueError("offline input must be BTC/USDT 1h")
    items = raw.get("candles")
    if not isinstance(items, list):
        raise ValueError("offline candles must be a list")
    if len(items) > 5000:
        raise ValueError("more than 5000 H1 candles: choose a smaller historical window")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("offline candles must contain only objects")
    return [Candle.model_validate(item) for item in items]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Research-only Phase 5.7.5 realistic H1 execution stress")
    p.add_argument("--since", required=True, help="UTC inclusive H1 time e.g. 2026-06-01")
    p.add_argument("--until", required=True, help="UTC exclusive H1 time e.g. 2026-07-01")
    p.add_argument("--manifest", default="state/research/phase572_v2_manifest.json")
    p.add_argument("--report", required=True, help="NEW phase575_*.json path (fails if exists)")
    p.add_argument("--ohlcv-json", default=None, help="offline phase575_ohlcv_v1 file instead of API")
    p.add_argument("--gap-policy", choices=("reject", "segment"), default="reject")
    p.add_argument("--fee-rate", type=float, default=0.001)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    p.add_argument("--stop-extra-bps", type=float, default=3.0)
    p.add_argument("--gap-extra-bps", type=float, default=5.0)
    p.add_argument("--venue", choices=("spot", "futures"), default="spot")
    p.add_argument("--funding-rate-per-8h", type=float, default=0.0)
    return p.parse_args()


def main() -> int:
    a = parse_args()
    manifest = Path(a.manifest)
    output = Path(a.report)
    if not output.name.startswith("phase575_") or output.suffix != ".json":
        raise ValueError("report name must start phase575_ and end .json")
    sources = [manifest]
    if a.ohlcv_json:
        sources.append(Path(a.ohlcv_json))
    if any(output.resolve() == source.resolve() for source in sources):
        raise ValueError("output cannot overwrite any source or frozen manifest")
    if output.exists():
        raise FileExistsError("research stress report already exists; choose a new filename")
    since = _parse_hour(a.since)
    until = _parse_hour(a.until)
    if since >= until or (until - since) // HOUR_MS > 5000:
        raise ValueError("select a non-empty study window of at most 5000 H1 candles")
    m: Any = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(m, dict):
        raise ValueError("frozen manifest must be a JSON object")
    # Validate scope and hashes BEFORE network requests, not after downloading OOS.
    from app.research.candidate_v2_research import CandidateV2Research

    CandidateV2Research().forward_validate([], manifest=m)
    if until > int(ExecutionRealismStudy._time(m["discovery_cutoff"]).timestamp() * 1000):
        raise ValueError("study cannot fetch previously observed forward/OOS data")
    config = ExecutionRealismConfig(
        fee_rate=a.fee_rate,
        slippage_bps=a.slippage_bps,
        stop_extra_slippage_bps=a.stop_extra_bps,
        gap_extra_slippage_bps=a.gap_extra_bps,
        venue=a.venue,
        funding_rate_per_8h=a.funding_rate_per_8h,
    )
    if a.ohlcv_json:
        candles = _load_candles(Path(a.ohlcv_json))
        source = "explicit_offline_phase575_ohlcv_v1"
    else:
        candles = BinancePublicOHLCV().fetch_range("BTC/USDT", "1h", since_ms=since, until_ms=until)
        source = "binance_spot_public_historical_ohlcv"
    report = ExecutionRealismStudy().run(
        candles=candles,
        manifest=m,
        config=config,
        since_ms=since,
        until_ms=until,
        gap_policy=a.gap_policy,
        source=source,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: no overwriting any existing report or evidence.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({
        "phase": "5.7.5", "report": str(output),
        "manifest_hash": report["manifest_hash"],
        "comparisons": report["comparisons"],
        "promotion_allowed": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())