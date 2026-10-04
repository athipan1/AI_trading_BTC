from __future__ import annotations

import argparse
import json

from app.research.oos_milestones import OOSMilestoneEvidenceHistory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record immutable Phase 5.6.8 OOS milestone evidence snapshots."
    )
    parser.add_argument("--promotion", required=True)
    parser.add_argument("--integrity", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--history", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    recorder = OOSMilestoneEvidenceHistory()
    result = recorder.record(
        promotion_path=args.promotion,
        integrity_path=args.integrity,
        checkpoint_path=args.checkpoint,
        history_path=args.history,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
