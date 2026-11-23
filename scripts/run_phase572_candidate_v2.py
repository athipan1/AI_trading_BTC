"""Freeze Candidate V2 on discovery, or validate only new post-freeze OOS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.research.candidate_v2_research import CandidateV2Research
from app.research.historical_store import HistoricalResearchStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 5.7.2/5.7.3 research-only Candidate V2")
    parser.add_argument("--mode", choices=("discover", "forward"), required=True)
    parser.add_argument("--discovery-store", help="Canonical historical discovery store (discover only)")
    parser.add_argument("--future-oos-store", help="Only genuinely new post-freeze OOS (forward only)")
    parser.add_argument("--manifest", required=True, help="Immutable V2 manifest path")
    parser.add_argument("--report", required=True, help="New separate report output path")
    return parser.parse_args()


def _safe_output(paths: list[str | None], report_path: Path) -> None:
    if any(report_path.resolve() == Path(path).resolve() for path in paths if path is not None):
        raise ValueError("output path must differ from every input evidence and manifest path")
    if report_path.exists():
        raise FileExistsError("report exists; choose a new output path (no overwrite)")


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    """Fail closed on existing artifacts. No operational state writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest)
    report_path = Path(args.report)
    _safe_output(
        [args.discovery_store, args.future_oos_store, args.manifest], report_path
    )
    if report_path.resolve() == manifest_path.resolve():
        raise ValueError("report and manifest paths must differ")
    researcher = CandidateV2Research()
    if args.mode == "discover":
        if not args.discovery_store or args.future_oos_store:
            raise ValueError("discover requires only --discovery-store, never OOS")
        if manifest_path.exists():
            raise FileExistsError("candidate frozen manifest exists; refusing to retune")
        trades = HistoricalResearchStore(args.discovery_store).load()
        report, manifest = researcher.discover(trades)
        _write_once(manifest_path, manifest)
        _write_once(report_path, report)
    else:
        if not args.future_oos_store or args.discovery_store:
            raise ValueError("forward requires only --future-oos-store (no discovery retuning)")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("frozen manifest must be a JSON object")
        trades = HistoricalResearchStore(args.future_oos_store).load()
        report = researcher.forward_validate(trades, manifest=manifest)
        _write_once(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())