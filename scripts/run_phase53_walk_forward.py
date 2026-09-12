from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.research.historical_store import HistoricalResearchStore
from app.research.walk_forward import WalkForwardResearch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 5.3 expanding walk-forward validation"
    )
    parser.add_argument("--store", default=None, help="Historical research store JSON path")
    parser.add_argument("--output", default=None, help="Optional JSON report output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    store_path = args.store or settings.research_historical_trade_store
    historical = HistoricalResearchStore(store_path).load()
    report = WalkForwardResearch().run(historical)

    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Historical research store: {store_path}")
    print(payload)

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(f"Phase 5.3 report: {output}")


if __name__ == "__main__":
    main()
