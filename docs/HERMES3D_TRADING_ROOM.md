# Hermes3D Trading Room

Phase 1.7 runs the real Hermes3D Studio against the AI Trading BTC FastAPI runtime through Hermes3D's `custom` runtime seam, keeps the observability path independent from CCXT/exchange access, and maps normalized trading events into the existing Hermes3D office agent state machine.

## Safety boundary

This integration is read-only.

Hermes3D can read:

- `GET /health`
- `GET /registry`
- `GET /state`
- `GET /events/stream` (Server-Sent Events)
- `WS /events/ws` (WebSocket)

The Trading Room same-origin proxy exposes only HTTP `GET`. It has no route for order placement, order cancellation, position modification, or execution.

The AI Trading BTC `/state` payload reports:

- `trade_execution: false`
- `order_cancel: false`
- `position_modify: false`
- `risk.execution_enabled: false`

## CCXT-free observability

`/state`, `/events/stream`, and `/events/ws` do not fetch Binance market data. They reconstruct observable state from the append-only Hermes3D event journal plus the existing position and automation state files.

This lets a dedicated Ubuntu/proot or dashboard runtime operate without CCXT or Binance credentials. If no trading-worker event has been published yet, `/state` remains healthy and returns `degraded: true` with nullable market metrics instead of failing with `MarketDataError`.

## Zero-downtime legacy sidecar

Phase 1.6.2 adds `scripts/run_hermes3d_sidecar.py` for traders that were started before the journal publisher code was loaded. The sidecar tails the existing JSON stdout logs, converts only observable trading results into normalized Hermes3D events, and writes them to `state/hermes3d-events.jsonl`.

The sidecar never imports an exchange broker, never reads Binance API credentials, and never mutates trader state. By default it attaches at the current end of each log so historical BUY/SELL events are not replayed into the live room. Byte offsets are persisted in `state/hermes3d-sidecar-cursors.json`, so restarting the sidecar does not replay already-consumed lines.

Native Termux example:

```bash
cd ~/AI_trading_BTC
nohup python scripts/run_hermes3d_sidecar.py \
  --spot-log spot-long.log \
  --futures-log futures-short.log \
  --event-journal state/hermes3d-events.jsonl \
  --cursor-store state/hermes3d-sidecar-cursors.json \
  --interval-seconds 1 \
  > hermes3d-sidecar.log 2>&1 &
```

Do not use `--from-start` on a live trading account unless deliberate historical event replay is desired.

## Realtime architecture

Current Phase 1.6 workers publish directly to:

```text
state/hermes3d-events.jsonl
```

Already-running legacy workers can be observed through the sidecar:

```text
spot-long.log + futures-short.log
              |
              v
Hermes3D read-only sidecar
              |
              v
state/hermes3d-events.jsonl
              |
              v
FastAPI SSE/WebSocket -> Hermes3D Trading Room / 3D Office
```

Normalized event types include:

- `BUY_READY`
- `SHORT_READY`
- `RISK_PASS`
- `ORDER_OPEN`
- `TP_HIT`
- `SL_HIT`
- `CIRCUIT_BREAKER`

A `STATE_SNAPSHOT` is sent when a client connects and again after observable state changes so the Trading Room remains synchronized without browser polling.

## Phase 1.7 realtime 3D agent animation mapping

The `/office` route now mounts `TradingOfficeRealtimeBridge` inside Hermes3D's existing `AgentStoreProvider`. The bridge holds one same-origin `EventSource` connection to the read-only trading event endpoint and maps trading events into the existing Hermes3D agent `status`, `runId`, `streamText`, and activity fields. Hermes3D already interprets a running agent as working in the 3D scene, so this extends the pinned architecture rather than adding a parallel renderer.

Event mapping:

```text
BUY_READY / SHORT_READY -> strategy agent RUNNING for 8s
RISK_PASS               -> risk-manager RUNNING for 7s + strategy pulse for 4s
ORDER_OPEN              -> positions RUNNING for 10s
TP_HIT                  -> positions RUNNING for 12s
SL_HIT                  -> positions ERROR for 12s
CIRCUIT_BREAKER         -> risk-manager ERROR until state/runtime recovery
```

The transient mappings automatically return agents to `idle` after their display window. `CIRCUIT_BREAKER` is intentionally persistent so the safety halt remains visually obvious.

The bridge does not call the FastAPI order routes, does not import broker/execution code, does not read API credentials, and does not mutate trading state. It only updates browser-side Hermes3D presentation state from the read-only SSE stream.

## Shared state paths for Termux + Ubuntu/proot

When traders remain in native Termux and FastAPI runs inside Ubuntu/proot, point the read-only runtime at the native Termux state directory. Example:

```bash
export HERMES3D_SPOT_POSITION_STORE=/data/data/com.termux/files/home/AI_trading_BTC/state/binance-testnet-positions.json
export HERMES3D_FUTURES_POSITION_STORE=/data/data/com.termux/files/home/AI_trading_BTC/state/binance-futures-testnet-short-positions.json
export HERMES3D_BASELINE_STATE_STORE=/data/data/com.termux/files/home/AI_trading_BTC/state/binance-testnet-auto-baseline.json
export HERMES3D_TRIPLE_EMA_STATE_STORE=/data/data/com.termux/files/home/AI_trading_BTC/state/binance-testnet-auto-triple-ema.json
export HERMES3D_FUTURES_SHORT_STATE_STORE=/data/data/com.termux/files/home/AI_trading_BTC/state/binance-futures-testnet-short-auto.json
export HERMES3D_EVENT_JOURNAL=/data/data/com.termux/files/home/AI_trading_BTC/state/hermes3d-events.jsonl
```

The exact Termux home path may differ by installation. Verify it before starting FastAPI.

## Start

From the repository root:

```bash
docker compose -f docker-compose.yml -f docker-compose.hermes3d.yml up --build
```

Services:

- AI Trading BTC API: `http://localhost:8000`
- SSE event stream: `http://localhost:8000/events/stream`
- WebSocket event stream: `ws://localhost:8000/events/ws`
- Hermes3D Studio: `http://localhost:3000`
- Trading Room: `http://localhost:3000/trading`
- Hermes3D 3D office: `http://localhost:3000/office`

The compose overlay configures Hermes3D with:

```text
HERMES3D_GATEWAY_URL=http://btc-trader:8000
HERMES3D_GATEWAY_ADAPTER_TYPE=custom
AI_TRADING_RUNTIME_URL=http://btc-trader:8000
CUSTOM_RUNTIME_ALLOWLIST=btc-trader
```

`btc-trader` is the Docker Compose service hostname, so Hermes3D reaches FastAPI over the private Compose network instead of browser-side CORS.

## Live agent mapping

Hermes3D reads the `active` map from `/state` and materializes these observer agents:

- `market-data`
- `baseline`
- `triple_ema`
- `triple_ema_short`
- `risk-manager`
- `positions`

The `/trading` room and `/office` 3D scene each hold one same-origin SSE connection. Both consume the same normalized event stream, while `/office` translates events into the native Hermes3D working/error animation states.

## Event producers

Both current automatic trading entry points publish to the same journal by default:

```text
scripts/run_binance_testnet_auto.py
scripts/run_binance_futures_testnet_short.py
```

For already-running pre-Phase-1.6 processes, use:

```text
scripts/run_hermes3d_sidecar.py
```

Override the journal path with either:

```text
HERMES3D_EVENT_JOURNAL=/path/to/events.jsonl
```

or the command-line argument:

```text
--event-journal /path/to/events.jsonl
```

## Hermes3D source pin

The integration image builds from upstream `iamlukethedev/Hermes3D` at the pinned commit declared by `HERMES3D_REF` in `deploy/hermes3d/Dockerfile`.

Pinning avoids an upstream change silently breaking the production trading stack. Upgrade the pin deliberately and validate the Docker build before merging.

## Stop

```bash
docker compose -f docker-compose.yml -f docker-compose.hermes3d.yml down
```
