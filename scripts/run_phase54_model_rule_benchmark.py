from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.research.historical_store import HistoricalResearchStore
from app.research.model_rule_benchmark import BenchmarkConfig, ModelRuleBenchmark
from app.research.walk_forward import WalkForwardConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 5.4 model vs rule-based diagnostic benchmark"
    )
    parser.add_argument("--store", default=None, help="Historical research store JSON path")
    parser.add_argument("--output", default=None, help="Optional JSON report output path")
    parser.add_argument("--fold-count", type=int, default=4)
    parser.add_argument("--initial-train-fraction", type=float, default=0.40)
    parser.add_argument("--validation-fraction", type=float, default=0.07)
    parser.add_argument("--test-fraction", type=float, default=0.07)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    store_path = args.store or settings.research_historical_trade_store
    historical = HistoricalResearchStore(store_path).load()
    walk_forward_config = WalkForwardConfig(
        fold_count=args.fold_count,
        initial_train_fraction=args.initial_train_fraction,
        validation_fraction=args.validation_fraction,
        test_fraction=args.test_fraction,
    )
    report = ModelRuleBenchmark(
        walk_forward_config=walk_forward_config,
        benchmark_config=BenchmarkConfig(),
    ).run(historical)

    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Historical research store: {store_path}")
    print(payload)

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(f"Phase 5.4 report: {output}")


if __name__ == "__main__":
    main()
