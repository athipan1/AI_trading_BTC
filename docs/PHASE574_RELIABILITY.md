# Phase 5.7.4 — Candidate V2 Research Reliability & Observability

**Research-only.** Adds an independent integrity auditor, watcher heartbeat,
read-only health projection, Hermes3D bilingual monitoring tabs, and deduplicated
LINE alerts. It does not trade, optimize/retrain a strategy, modify V1 promotion,
or mutate frozen 5.7.2/5.7.3 evidence. V2 remains **NOT AUTHORIZED** for production.

## Architecture

- `scripts/run_phase573_fresh_oos.py` remains the *sole* OOS writer and uses its
  original lock/checkpoint contract. After this upgrade it also writes
  `state/research/phase574_v2_heartbeat.json` **after each success or failure**
  (including attempts with no new closed trades). `last_success_at` does not
  advance on a failed attempt. This telemetry file is **not evidence**.
- `app/research/candidate_v2_integrity.py` independently verifies frozen manifest
  and policy hashes using the existing Phase 5.7.2 validator, V2 store schema,
  unique ID/strategy lineage, post-freeze entry timestamps, closed trades,
  fees/fills/realized-R consistency, Checkpoint pin, store hashes and counts.
  The separate `phase574_v2_audit_state.json` records previous trade fingerprints
  to detect deletion/rollback on later audits. It is never used for trading.
  **Local audit state is tamper-evident only relative to a trusted backup**:
  a malicious editor with full filesystem access could replace both evidence
  and monitoring state. Back up manifest and evidence independently, read-only.
- `app/research/candidate_v2_watchdog.py` evaluates the last heartbeat, last
  successful attempt, latest H1 checkpoint and audited evidence. **0 trades is
  not a failure.** No heartbeat yields `UNKNOWN`; corrupt evidence yields
  `CRITICAL`. A fresh attempt reporting an error yields at least `WARNING`.
- `scripts/run_phase574_monitor.py` runs in its **own OS process** using its
  **own lock**, independent from the OOS writer. It writes a sanitized health
  JSON read by `/research/operations.candidate_v2` when its filesystem is
  mounted into the API. V1 fields/schemas and V1 promotion remain unchanged.
- `candidate_v2_alerts.py` uses existing `LineMessagingNotifier` for optional
  LINE push; alert state advances only after a successful push, and alert
  recovery requires two healthy monitoring passes. Repeats at most hourly.

## Health / operational states

| State | Trigger |
| --- | --- |
| `HEALTHY` | Watcher in watch mode, heartbeat <=15 min, evidence and checkpoint valid/fresh |
| `WAITING` | Heartbeat healthy, valid manifest, but checkpoint not yet written |
| `UNKNOWN` | No watcher heartbeat yet; no untrusted assumption of health |
| `WARNING` | Heartbeat >15 min, failed last attempt, missing report or H1 lag >2h |
| `CRITICAL` | Heartbeat >30 min, prolonged watcher errors, H1 lag >4h, bad hash/lineage or corrupt telemetry |

Timing values are monitoring SLA defaults only, not strategy parameters. API
reports older than 15 minutes show `STALE` and cannot appear healthy.

## Termux — upgrade the existing watcher (exactly once)

Check the currently running process first and **do not start a duplicate**:

```bash
cd ~/AI_trading_BTC
git pull --ff-only
pgrep -af 'run_phase573_fresh_oos.py'
```

Stop the **identified** old Phase 5.7.3 watcher PID using `kill <PID>`. Do not
kill the production trading bot or V1 watcher. The existing V2 evidence and
`phase572_v2_manifest.json` must remain untouched. Then restart the upgraded
one and start the independent auditor:

```bash
mkdir -p state/research
nohup env PYTHONPATH=. python scripts/run_phase573_fresh_oos.py \
  --watch --interval-seconds 300 \
  > state/research/phase573_v2_watcher.log 2>&1 < /dev/null &
echo $! > state/research/phase573_v2_watcher.pid

nohup env PYTHONPATH=. python scripts/run_phase574_monitor.py \
  --watch --interval-seconds 300 \
  > state/research/phase574_v2_monitor.log 2>&1 < /dev/null &
echo $! > state/research/phase574_v2_monitor.pid
```

Optional LINE: add `--line-alerts` to the monitor command, with
`LINE_CHANNEL_ACCESS_TOKEN` and `LINE_TARGET_ID` in the environment **without
logging them**. If LINE is not configured, audit/health still work. A successful
message is needed before alert dedup state is updated.

To inspect:

```bash
pgrep -af 'run_phase57(3_fresh_oos|4_monitor).py'
tail -n 30 state/research/phase574_v2_monitor.log
python - <<'PY'
import json
with open('state/research/phase574_v2_health.json', encoding='utf-8') as handle:
    health = json.load(handle)
for field in ('operational_state', 'watcher_state', 'issues', 'counts', 'observed_at'):
    print(field, ':', health.get(field))
PY
```

A one-shot monitor exits code 2 if critical but still writes its report:

```bash
PYTHONPATH=. python scripts/run_phase574_monitor.py
```

`nohup` does not prevent Android from killing Termux. For 24/7 evidence and
watchdog, prefer a VPS with managed services and **one active evidence writer**.
Do not run a second writer on another host against the same store.

## Hermes3D / API deployment boundary

The API uses `RESEARCH_CANDIDATE_V2_HEALTH_REPORT` to read V2 health.
`/research/operations` includes a separate `candidate_v2` object and retains
V1 keys unchanged. The existing Next.js proxy uses
`/api/trading-runtime?resource=research-operations`; no new trading route.
The file must be visible to the API container/host via read-only mount or an
explicit authenticated sync mechanism. If it is only on Termux while API runs
on a VPS, Hermes3D will show `MISSING` rather than inventing live telemetry.

## Test and safety acceptance

```bash
ruff check .
pytest -q
```

Inject manifest edits, store/accounting edits, Checkpoint rollback, missing
heartbeat, stale heartbeat, no-new-trade waiting, invalid V2 report, LINE push
failure, concurrent monitor locking and API staleness. CI must also pass the
pinned Hermes3D build. Monitoring never changes the frozen policy or OOS data.