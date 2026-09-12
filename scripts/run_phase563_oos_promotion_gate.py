from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.research.frozen_oos_validation import FrozenOOSValidationResearch
from app.research.historical_store import HistoricalResearchStore
from app.research.oos_promotion_gate import OOSPromotionGate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 5.6.3 OOS evidence monitoring and frozen promotion gate"
    )
    parser.add_argument("--discovery-store", required=True)
    parser.add_argument("--oos-store", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--gate-manifest", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    discovery_trades = HistoricalResearchStore(args.discovery_store).load()
    oos_trades = HistoricalResearchStore(args.oos_store).load()
    frozen_manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))

    validator = FrozenOOSValidationResearch()
    validation = validator.validate(
        discovery_trades,
        oos_trades,
        manifest=frozen_manifest,
    )

    gate = OOSPromotionGate()
    gate_manifest = gate.load_or_freeze_gate_manifest(
        args.gate_manifest,
        frozen_manifest=frozen_manifest,
        validation_config=validation["config"],
    )
    report = gate.evaluate(validation, gate_manifest=gate_manifest)

    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    print(f"Phase 5.6.3 report: {output}")


if __name__ == "__main__":
    main()
