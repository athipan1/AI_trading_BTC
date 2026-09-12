# Phase 5.6 Frozen Regime Policy + Fresh OOS Validation

Phase 5.6 freezes the discovery-time ML and regime-policy decisions before evaluating any fresh out-of-sample trades.

## Research boundary

- Research only. No Binance, execution, accounting, or PositionStore mutation.
- Discovery data is the Phase 5.2-5.5 historical research store.
- OOS data must live in a separate historical research store.
- Every OOS `feature_available_at` must be strictly later than the discovery cutoff.
- Model, threshold, feature schema, and regime policy are frozen before OOS evaluation.
- OOS retuning is forbidden.

## Frozen candidate policy

Composite segments are keyed as `strategy_id|side|entry_market_regime`.

- `ROBUST` or `PROMISING`: apply the frozen global ML filter.
- `FAILURE`, `UNSTABLE`, or `INSUFFICIENT`: fall back to the rule-based signal for research comparison.
- Unseen segments: use the frozen global ML filter as the explicit default.

The manifest records hashes for the model contract, policy, and full manifest so changes are detectable.

## Three-arm comparison

Phase 5.6 evaluates:

1. Rule-based: all canonical strategy signals.
2. Global ML: the frozen Phase 5.2 model and validation-selected threshold.
3. Frozen regime policy: the frozen Phase 5.5 segment policy layered over the same ML output.

Validation and superiority are reported separately. A valid OOS experiment can pass structural/evidence/performance gates while failing to demonstrate superiority over global ML.

## Run

```bash
PYTHONPATH=. python scripts/run_phase56_frozen_oos_validation.py \
  --discovery-store /workspace/research/btc_h1_2021_2026_gap_aware.json \
  --oos-store /workspace/research/phase56_fresh_oos.json \
  --manifest-output /workspace/research/phase56_frozen_manifest.json \
  --output /workspace/research/phase56_frozen_oos_validation.json
```

Do not point `--oos-store` at the discovery store. The engine rejects overlapping timestamps.
