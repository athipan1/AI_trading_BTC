# Hermes3D Trading Room

Phase 1.6.1 runs the real Hermes3D Studio against the AI Trading BTC FastAPI runtime through Hermes3D's `custom` runtime seam and keeps the observability path independent from CCXT/exchange access.

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

`/state`, `/events/stream`, and `/events/ws` no longer fetch Binance market data. They reconstruct observable state from the append-only Hermes3D event journal plus the existing position and automation state files.

This lets a dedicated Ubuntu/proot or dashboard runtime operate without CCXT or Binance credentials. If no trading-worker event has been published yet, `/state` remains healthy and returns `degraded: true` with nullable market metrics instead of failing with `MarketDataError`.

The event stream also watches position and automation state files. This means already-running legacy workers can still surface new `ORDER_OPEN`, `TP_HIT`, `SL_HIT`, and `CIRCUIT_BREAKER` transitions even if those workers were started before the journal publisher code was loaded. `BUY_READY`, `SHORT_READY`, and `RISK_PASS` require a worker that publishes the Phase 1.6 event journal.

## Realtime architecture

The Spot and Futures auto-trading workers append normalized events to:

```text
state/hermes3d-events.jsonl
```

The FastAPI Hermes3D event stream tails that append-only journal at low latency and forwards events through SSE and WebSocket. No exchange order API is reachable from the event endpoints.

Normalized event types include:

- `BUY_READY`
- `SHORT_READY`
- `RISK_PASS`
- `ORDER_OPEN`
- `TP_HIT`
- `SL_HIT`
- `CIRCUIT_BREAKER`

A `STATE_SNAPSHOT` is sent when a client connects and again after observable state changes so the Trading Room remains synchronized without browser polling.

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

The `/trading` room holds one same-origin SSE connection and updates agent status as normalized trading events arrive. The backend also exposes the equivalent WebSocket stream for future 3D-office runtime-event integration.

## Event producers

Both automatic trading entry points publish to the same journal by default:

```text
scripts/run_binance_testnet_auto.py
scripts/run_binance_futures_testnet_short.py
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
