from __future__ import annotations

import argparse
import json

from app.config import get_settings
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.historical_diagnostics import HistoricalResearchDiagnostics
from app.research.historical_store import HistoricalResearchStore
from app.research.runtime_acceptance import evaluate_phase51_runtime_acceptance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Phase 5.1 runtime acceptance on the persisted historical research store"
    )
    parser.add_argument("--store", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    store_path = args.store or settings.research_historical_trade_store

    historical = HistoricalResearchStore(store_path).load()
    diagnostics = HistoricalResearchDiagnostics.build(historical)
    quality = ResearchFeatureDatasetProjection.quality(
        [], historical_trades=historical, source="historical"
    )
    split = ResearchFeatureDatasetProjection.temporal_split(
        [], historical_trades=historical, source="historical"
    )
    acceptance = evaluate_phase51_runtime_acceptance(
        diagnostics=diagnostics,
        quality=quality,
        split=split,
        production_position_store_mutated=False,
    )

    print(f"Historical research store: {store_path}")
    print(f"Phase 5.1 runtime acceptance: {json.dumps(acceptance, sort_keys=True)}")
    if acceptance["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
