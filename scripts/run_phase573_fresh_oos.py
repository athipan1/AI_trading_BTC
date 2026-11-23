"""Phase 5.7.3: collect new BTC/USDT H1 Candidate V2 OOS without trading.

Termux-compatible: only requests plus existing light research dependencies.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.research.binance_public_ohlcv import BinancePublicOHLCV
from app.research.candidate_v2_forward import CandidateV2ForwardAccumulator

LOGGER = logging.getLogger("phase573_fresh_oos")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Accumulate frozen Candidate V2 post-freeze H1 OOS")
    parser.add_argument(
        "--manifest",
        default="state/research/phase572_v2_manifest.json",
        help="Existing Phase 5.7.2 frozen manifest; never regenerated",
    )
    parser.add_argument(
        "--candidate-store",
        default="state/research/phase573_v2_candidate_oos.json",
    )
    parser.add_argument(
        "--baseline-store",
        default="state/research/phase573_v2_baseline_oos.json",
    )
    parser.add_argument(
        "--checkpoint",
        default="state/research/phase573_v2_checkpoint.json",
    )
    parser.add_argument(
        "--report",
        default="state/research/phase573_v2_latest_report.json",
    )
    parser.add_argument("--until", default=None, help="UTC exclusive, fully closed H1 boundary")
    parser.add_argument("--watch", action="store_true", help="Poll hourly; no exchange orders")
    parser.add_argument("--interval-seconds", type=int, default=300)
    return parser.parse_args()


def _read_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("frozen Candidate V2 manifest must be a JSON object")
    return payload


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


@contextmanager
def _exclusive_watcher_lock(checkpoint_path: Path) -> Iterator[None]:
    """Prevent two watchers corrupting the same append-only evidence stores."""
    lock_path = checkpoint_path.with_suffix(checkpoint_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Phase 5.7.3 is already running on this checkpoint") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main() -> int:
    args = parse_args()
    if args.watch and args.until is not None:
        raise ValueError("--watch cannot be combined with a fixed --until")
    if args.interval_seconds < 60:
        raise ValueError("--interval-seconds must be at least 60")
    paths = [
        Path(args.manifest),
        Path(args.candidate_store),
        Path(args.baseline_store),
        Path(args.checkpoint),
        Path(args.report),
    ]
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("all manifest, OOS evidence, checkpoint and report paths must differ")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    accumulator = CandidateV2ForwardAccumulator()
    market_data = BinancePublicOHLCV()
    with _exclusive_watcher_lock(paths[3]):
        while True:
            try:
                manifest = _read_manifest(paths[0])
                report = accumulator.run(
                    manifest=manifest,
                    market_data=market_data,
                    candidate_store_path=paths[1],
                    baseline_store_path=paths[2],
                    checkpoint_path=paths[3],
                    requested_until=args.until,
                )
                _write_report(paths[4], report)
                LOGGER.info(
                    "Phase 5.7.3 %s: candidate_closed=%s baseline_closed=%s",
                    report["state"],
                    report["counts"]["candidate_v2_closed"],
                    report["counts"]["canonical_rule_based_closed"],
                )
                if not args.watch:
                    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                    return 0
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                LOGGER.exception("Phase 5.7.3 rejected unsafe/incomplete input: %s", exc)
                if not args.watch:
                    return 1
            if not args.watch:
                return 0
            try:
                time.sleep(args.interval_seconds)
            except KeyboardInterrupt:
                LOGGER.info("Phase 5.7.3 watcher stopped")
                return 0


if __name__ == "__main__":
    raise SystemExit(main())