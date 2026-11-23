"""Phase 5.7.1 read-only frozen-OOS gate diagnostics CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.research.oos_diagnostics import OOSPromotionDiagnostics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Phase 5.6.3 promotion (research-only)")
    parser.add_argument("--promotion", type=Path, required=True)
    parser.add_argument("--integrity", type=Path, default=None)
    parser.add_argument("--history", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected at {path}")
    return payload


def main() -> int:
    args = parse_args()
    sources = [path for path in (args.promotion, args.integrity, args.history) if path is not None]
    if args.output.resolve() in {path.resolve() for path in sources}:
        raise ValueError("--output cannot replace an evidence artifact")

    report = OOSPromotionDiagnostics.analyze(
        load_json(args.promotion),
        integrity=load_json(args.integrity) if args.integrity else None,
        milestone_history=load_json(args.history) if args.history else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())