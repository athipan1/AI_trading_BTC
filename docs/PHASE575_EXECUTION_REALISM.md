# Phase 5.7.5 — Execution Realism & Market Stress Study

**Research-only, exploratory historical discovery simulation.** Does not replace
`HistoricalStrategyReplay`, does not change the frozen Candidate V2 manifest or
Phase 5.7.3/5.7.4 stores/checkpoints/heartbeats, does not train/retune on OOS,
and never authorizes live/testnet order execution or production promotion.

## Why a parallel engine?

The canonical `HistoricalStrategyReplay` submits orders at next-bar open and
closes on strategy EXIT signals, but does **not** independently execute SL/TP
inside an H1 candle. This can materially overstate or understate performance.
`ExecutionRealismReplay` keeps the same `ReplayStrategy`/`TradeSignal` contract,
so the **same** Triple EMA and frozen Candidate V2 confirmed entry filters can
be simulated side-by-side, without modifying the original evidence-generating
engine. No historical output is appended to Phase 5.7.3 evidence.

## Deterministic, predeclared scenario assumptions

- Entry and strategy EXIT orders use the **following H1 bar open** (never the
  signal candle close). No look-ahead on entry decisions.
- Initial SL is assumed a continuously active stop-market trigger, including
  on the entry bar. Optional TP is treated as a *market trigger* (not guaranteed
  passive limit fill). If both are hit in one H1 bar, resolve **SL FIRST**,
  record `intrabar_sl_tp_ambiguous=true`. We cannot know the true tick path.
- If an existing position gaps through its stop at a bar open, execute at that
  *open*, not the stop level. Extra stop and gap slippage assumptions are adverse;
  fees apply on both fills. Price paths and exact time within a bar cannot be
  observed in OHLCV alone. This is a conservative bar-based stress backtest,
  **not** a full exchange/order-book execution simulator.
- For the canonical Triple EMA Long, `stop_loss=EMA50` is a **risk reference**
  in the current live contract, not necessarily a fixed intrabar stop order.
  Turning it into an active fixed initial stop in this study is a *what-if*
  assumption. Do not imply it matches deployed trading or label the results a
  verified live strategy fill.
- No order-book depth, fill queue, liquidity, minimum notional filters, margin,
  liquidation, hedging, dynamic trailing SL, or portfolio mark-to-market.
- Venue defaults to `spot` with zero funding. With `--venue futures`, an
  explicit `--funding-rate-per-8h` can apply a *static funding sensitivity*
  every completed 8h of holding, signed by side; it is **not exchange funding
  history**, and timing within the candle is unknown. No real fee schedule is
  fetched or claimed. Short signals on public Spot candles are **synthetic
  short stress scenarios**, not Spot short executions.
- Open trades at the end of the input are excluded from realized statistics.
  A source-data gap resets strategy state in `--gap-policy segment` mode; no
  fake candles or carry-over positions. `reject` is the default gap policy.

## Data separation and frozen protection

The runner requires the original frozen `phase572_v2_manifest.json`. It verifies
its hashes and rejects any candle range whose **exclusive end** exceeds the
manifest's `discovery_cutoff`, so no new OOS or post-freeze candles enter this
study. Only **closed historical discovery H1** data is used. A separate report
is created **once** under a new name `phase575_*.json`. The report includes
candlestick source SHA256, frozen manifest/policy pins, cost assumptions, gap
coverage and legacy-vs-stress results, without mutating any OOS evidence.

This is a diagnostic **on previously seen discovery data**, not an independent
confirmation of candidate superiority. Do not choose or adjust frozen V2
features/thresholds after reading the report.

## Termux example: public Binance Spot market-data-only endpoint

```bash
cd ~/AI_trading_BTC
git pull --ff-only
PYTHONPATH=. python scripts/run_phase575_execution_realism.py \
  --since 2026-06-01 --until 2026-07-01 \
  --manifest state/research/phase572_v2_manifest.json \
  --report state/research/phase575_june2026_stress.json
```

The `--until` boundary is **exclusive UTC** and must be no later than the
manifest `discovery_cutoff`. The default public source is
`https://data-api.binance.vision/api/v3/klines`, read-only without API keys.
Each run allows at most **5,000** candles to keep Termux simulation bounded;
use separate unique reports for additional discovery windows.

Offline import requires **raw candles**, not `btc_h1_2021_2026_gap_aware.json`
if that file contains `historical_research_store_v1` *trades*. The explicit
OHLCV JSON schema is:

```json
{
  "schema_version": "phase575_ohlcv_v1",
  "symbol": "BTC/USDT",
  "timeframe": "1h",
  "candles": [
    {"timestamp_ms": 1780272000000, "open": 100, "high": 101,
     "low": 99, "close": 100.5, "volume": 1}
  ]
}
```

Use the `--ohlcv-json /path/to/phase575_raw_ohlcv.json` flag to avoid network
calls. Data provenance is checked against the requested UTC range. Pass
`--gap-policy segment` only when consciously accepting source gaps; each
continuous segment rewarms strategy independently.

To test a synthetic futures funding *sensitivity* (not historical funding):

```bash
PYTHONPATH=. python scripts/run_phase575_execution_realism.py \
  --since 2026-06-01 --until 2026-07-01 \
  --venue futures --funding-rate-per-8h 0.0001 \
  --manifest state/research/phase572_v2_manifest.json \
  --report state/research/phase575_june2026_futures_stress.json
```

## Acceptance tests

```bash
pytest -q tests/test_phase575_execution_realism.py tests/test_phase575_study.py
ruff check app/research/execution_realism.py app/research/execution_realism_study.py \
  scripts/run_phase575_execution_realism.py tests/test_phase575_execution_realism.py \
  tests/test_phase575_study.py
```

Test long/short SL and TP, H1 close recovery after stop, stop-first tie,
next-open gap, fees/slippage, open-position exclusion, synthetic funding,
bar validation, missing data, new immutable report, frozen policy pins and
strict discovery embargo. CI also checks the entire existing suite and
Hermes3D container build.