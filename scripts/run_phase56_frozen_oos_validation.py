from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.research.frozen_oos_validation import FrozenOOSValidationResearch
from app.research.historical_store import HistoricalResearchStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 5.6 frozen regime policy and fresh OOS validation"
    )
    parser.add_argument(
        "--discovery-store",
        required=True,
        help="Historical research store used for Phase 5.2-5.5 discovery",
    )
    parser.add_argument(
        "--oos-store",
        required=True,
        help="Fresh historical research store strictly after discovery cutoff",
    )
    parser.add_argument(
        "--manifest-output",
        default=None,
        help="Optional frozen manifest JSON output path",
    )
    parser.add_argument("--output", default=None, help="Optional Phase 5.6 report output path")
    return parser.parse_args()


def _write(path: str | None, payload: dict[str, object]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    discovery = HistoricalResearchStore(args.discovery_store).load()
    oos = HistoricalResearchStore(args.oos_store).load()
    research = FrozenOOSValidationResearch()
    manifest = research.freeze_manifest(discovery)
    report = research.validate(discovery, oos, manifest=manifest)

    print(f"Discovery research store: {args.discovery_store}")
    print(f"Fresh OOS research store: {args.oos_store}")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    _write(args.manifest_output, manifest)
    _write(args.output, report)
    if args.manifest_output:
        print(f"Phase 5.6 frozen manifest: {args.manifest_output}")
    if args.output:
        print(f"Phase 5.6 report: {args.output}")


if __name__ == "__main__":
    main()
