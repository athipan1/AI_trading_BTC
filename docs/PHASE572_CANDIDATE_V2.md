# Phase 5.7.2 Candidate V2: entry-quality research and new-OOS isolation

Phase 5.7.2 builds a **research-only** Candidate V2 on top of existing Phase 4/5
canonical Triple EMA replay trades and entry-time features. The implemented strategy
adapter (`CandidateV2ReplayStrategy`) can be passed to the existing
`HistoricalStrategyReplay` for subsequent end-to-end replay, but **it is not a
production/exchange strategy**.

## Safety constraints

- No changes to V1 Frozen Regime Policy, Promotion Gate, Hermes3D, PositionStore,
  accounting, Binance execution, or OOS milestone evidence.
- **Never supply the already-seen Phase 5.6 OOS store as discovery data.** This
  would contaminate Candidate V2 selection and invalidate future-OOS evaluation.
- Two entry-quality hypotheses (`balanced`, `confirmed`) are pre-registered and
  use existing entry-time ATR%, RSI, volume ratio, EMA slopes, and trend strength.
  These filters do not use realized PnL, exit reason, or future candles as inputs.
- Three forward chronological splits purge incomplete training and validation
  labels; each fold chooses a policy using *only that fold's validation data*.
  The final policy is selected from the pooled purged **discovery validation**
  observations, not fold tests or the last discovery holdout.
- Source outcomes are **realized R net of original replay fees and slippage**.
  The study verifies this from stored fills, commission, quantity, and risk.
  Missing/inconsistent costs or discarded/duplicate research trades are rejected.
- This is a **signal-level filtering counterfactual**: skipping entries can
  change available subsequent signals. It is **not a full portfolio backtest**.
  Do not treat positive metrics as permission to trade. For deployment candidates,
  run the `CandidateV2ReplayStrategy` through the canonical replay over fresh OHLCV,
  audit actual trade paths and SL/TP mechanics, and pass an independent safety gate.
- Frozen timestamp and manifest hashes are used to **reject any Phase 5.6 OOS
  signal observed before the Candidate V2 freeze**. Only later OOS is eligible.
- Candidate V2 **never automatically promotes** to production, even if OOS metrics
  are positive. A separate approval/implementation phase is mandatory.

## Running from Termux

Phase 5.7.2 discovery/forward score calculation uses a dependency-free metrics
helper and no longer imports scikit-learn or NumPy. The full ML research phases
still require the scientific Python stack. The Candidate V2 CLI still requires
the repository's other dependencies (notably Pydantic for replay model contracts).

The paths below are **illustrations**, not literal filenames. On Termux, first
locate existing research stores:

```bash
cd ~/AI_trading_BTC
find "$HOME" -type f \\( -name '*promotion*.json' -o -name '*historical*.json' \\) 2>/dev/null | head -40
```

A missing historical discovery store cannot be replaced with the already-inspected
Phase 5.6 OOS file. If the data lives on a VPS or Docker volume, execute the
discovery CLI where the historical research store actually exists.

## Run discovery (once)

Use the existing Phase 5.1 historical **discovery** replay store, NOT the V1
`phase56_fresh_oos.json` or any equivalent already-inspected OOS store.

```bash
PYTHONPATH=. python scripts/run_phase572_candidate_v2.py \
  --mode discover \
  --discovery-store /workspace/research/btc_h1_2021_2026_gap_aware.json \
  --manifest /workspace/research/phase572_v2_manifest.json \
  --report /workspace/research/phase572_v2_discovery_report.json
```

Paths are examples; use your actual paths. The manifest and report paths must
not already exist; rerunning with existing manifest is intentionally blocked to
prevent retuning a frozen experiment. Do not delete a manifest just to pick a
policy that performs better on old OOS.

## Validate genuine *new* post-freeze OOS

Only after accumulating **new** trades whose decision timestamps are strictly
after the manifest's `frozen_at` value:

```bash
PYTHONPATH=. python scripts/run_phase572_candidate_v2.py \
  --mode forward \
  --future-oos-store /workspace/research/phase572_post_freeze_oos.json \
  --manifest /workspace/research/phase572_v2_manifest.json \
  --report /workspace/research/phase573_fresh_oos_report.json
```

This CLI does not fetch/generate OOS itself, does not modify any store, and fails
closed if a supplied OOS trade predates the candidate freeze or overlaps any
recorded discovery order ID. No automatic production promotion is supported.

## Tests

```bash
ruff check .
pytest -q tests/test_phase572_candidate_v2.py
```

`EntryQualityPolicy.passes` is the single source of truth for the offline
candidate and the reusable replay adapter. Both rely on the existing
`build_entry_time_features` and `HistoricalStrategyReplay` contracts.