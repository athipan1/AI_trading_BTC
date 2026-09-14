from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.research.evidence_integrity import EvidenceIntegrityAuditor, EvidenceIntegrityConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Phase 5.6.2 Forward OOS evidence integrity without mutating evidence.",
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--oos-store", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--boundary", default="2026-09-01T00:00:00+00:00")
    parser.add_argument("--stale-after-seconds", type=float, default=108_000.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    auditor = EvidenceIntegrityAuditor(
        config=EvidenceIntegrityConfig(
            boundary_iso=args.boundary,
            stale_after_seconds=args.stale_after_seconds,
        )
    )
    previous_state = auditor.load_state(args.state)
    report, next_state = auditor.audit(
        manifest_path=args.manifest,
        oos_store_path=args.oos_store,
        checkpoint_path=args.checkpoint,
        previous_state=previous_state,
    )

    auditor.write_json(args.output, report)
    if report["integrity_ok"]:
        auditor.write_json(args.state, next_state)

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"Phase 5.6.5 report: {Path(args.output)}")
    if not report["integrity_ok"]:
        print("Phase 5.6.5 integrity audit failed; downstream promotion evaluation is blocked.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
