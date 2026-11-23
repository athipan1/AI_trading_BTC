# Phase 5.7.3: Frozen Candidate V2 Fresh OOS (Termux / VPS)

Runs a **research-only**, fee/slippage-aware **full canonical strategy replay**
with a frozen Candidate V2 entry filter and separate unfiltered Triple EMA baseline.
It never submits orders, updates positions, retrains V2, or changes Phase 5.6 V1
OOS, Promotion Gate, or Hermes3D. This is not a production-trading approval.

## Inputs and constraints

- The *existing* `state/research/phase572_v2_manifest.json` from Discovery must
  be present. Never regenerate or delete this frozen manifest.
- The script verifies its SHA256 manifest/policy hashes **before** network calls
  or evidence writes, and checks it again during forward validation.
- The minimum decision-candle timestamp is **strictly after the actual
  `frozen_at` field**, not simply after the end of the discovery dataset. For
  the current user's freeze, this means after 2026-11-23T16:52:54 UTC.
- Uses only complete, **closed BTC/USDT H1 candles** fetched with read-only
  `GET https://data-api.binance.vision/api/v3/klines`, without keys, CCXT,
  NumPy, or scikit-learn. Missing/delayed candles cause fail-closed without
  advancing the checkpoint.
- Replays 300 H1 warmup candles before the freeze and then all post-freeze data
  to retain deterministic strategy/position continuity across days. This is
  deliberately cumulative, not a rolling window that would truncate live
  trades; as the OOS horizon grows, replay time and API paging also grow.
- The entry quality filter comes solely from the frozen manifest. Both long
  and short canonical strategy replays use existing `HistoricalStrategyReplay`
  logic with **next-candle opens** and configurable cost assumptions pinned in
  the checkpoint (default fee 0.1%/side, slippage 2bps/side, qty 0.001 BTC).
  **Important:** This canonical engine closes on strategy exits; it does *not*
  model independent intrabar stop/TP executions. Do not treat results as an
  execution-grade backtest.
- Closed trades only are appended using the existing immutable
  `HistoricalResearchStore.append_immutable_replay` contract. Incomplete/open
  positions do not appear in evidence until they close. Replaying from the same
  pre-freeze boundary preserves the state necessary to capture those exits.
- Two **separate new stores** record candidate and baseline trades, with
  lineage hashes, replay configuration, pinned manifest, and idempotent
  checkpoint. Existing V1 data must NEVER be supplied as either store.
- Repeated identical H1 boundaries cause no new writes. Any detected source
  revision, historical mutation, changed replay costs, or checkpoint drift
  fails closed for manual review. Outputs stay under `state/research/` and must
  be backed up when moving to another Android device/VPS.
- The report compares **independently replayed** V2 and canonical unfiltered
  strategies. It is NOT a frozen V1 ML-policy-vs-V2 performance comparison and
  is not permission to deploy V2. There is no automatic Promotion Gate.

## Termux installation and one-time run

```bash
cd ~/AI_trading_BTC
git pull --ff-only
python -m pip install -r requirements-testnet-termux.txt
PYTHONPATH=. python scripts/run_phase573_fresh_oos.py
```

Expected immediate result after freeze, before any closed eligible trades:
`AWAITING_CLOSED_H1` or `AWAITING_CLOSED_V2_TRADES`. No old OOS is counted.

## Run every 5 minutes in the background (optional)

```bash
cd ~/AI_trading_BTC
mkdir -p state/research
nohup env PYTHONPATH=. python scripts/run_phase573_fresh_oos.py \
  --watch --interval-seconds 300 \
  > state/research/phase573_v2_watcher.log 2>&1 < /dev/null &
echo $! > state/research/phase573_v2_watcher.pid
```

Check status without changing evidence:

```bash
tail -n 30 state/research/phase573_v2_watcher.log
cat state/research/phase573_v2_latest_report.json
```

On Android, keep the device and Termux alive (disable battery optimization);
`nohup` cannot guarantee execution if Android kills Termux. VPS/systemd is
recommended for long-running monitoring. Only run one watcher against a store.
The `--until` flag may be used in one-shot mode to test a known closed UTC H1
boundary, but cannot be used with `--watch`.

## Tests

```bash
pytest -q tests/test_phase573_fresh_oos.py
ruff check app/research/binance_public_ohlcv.py app/research/candidate_v2_forward.py scripts/run_phase573_fresh_oos.py tests/test_phase573_fresh_oos.py
```