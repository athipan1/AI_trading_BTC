# Phase 5.7.1: Frozen OOS Rejection Diagnostics

This phase **does not alter** Phase 5.6's frozen model, selected threshold, regime policy,
append-only OOS evidence, Binance Testnet execution, accounting, or Hermes3D gate decisions.
It only diagnoses the current, existing Phase 5.6.3 promotion report.

## Run on the existing research artifacts

```bash
PYTHONPATH=. python scripts/run_phase57_oos_diagnostics.py \
  --promotion /workspace/research/phase563_promotion_gate.json \
  --integrity /workspace/research/phase565_evidence_integrity.json \
  --history /workspace/research/phase568_milestone_history.json \
  --output /workspace/research/phase57_oos_diagnostics.json
```

These paths are **examples**, not fixed filenames. Locate the actual paths used by
Phase 5.6.3 / 5.6.5 / 5.6.8 in the running environment. The promotion path is required.
The integrity and history inputs are optional; omission is reported as unverified or
no milestone history. The output must be a different file from every input.

The report separates not-yet-evaluated superiority checks from true failures,
describes the frozen acceptance checks in their original terms, compares current
policy performance against global ML, and verifies the Phase 5.6.8 milestone hash
chain and candidate pin when history is given. Numerical differences are **diagnostics,
not new acceptance rules**. An OOS signal count above 20 never overrides REJECT.

For safe Candidate V2 research, form and select hypotheses using discovery / separate
new training data, walk-forward validate with costs, freeze parameters, then test on
future untouched OOS. **Never** optimize V1 on already-seen OOS samples. The Phase 5.7.1
report cannot approve a candidate for execution.

## Tests

```bash
pytest -q tests/test_phase57_oos_diagnostics.py
ruff check app/research/oos_diagnostics.py scripts/run_phase57_oos_diagnostics.py tests/test_phase57_oos_diagnostics.py
```