# Hermes3D Trading Room

Phase 1.6 runs the real Hermes3D Studio against the AI Trading BTC FastAPI runtime through Hermes3D's `custom` runtime seam and adds a read-only realtime event bus.

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

A `STATE_SNAPSHOT` is sent when a client connects and again after each trading-event batch so the Trading Room state remains synchronized without browser polling.

The base Docker Compose file bind-mounts `./state` into `/app/state`. This lets the FastAPI container observe state and event files written by auto-trading workers running from the same self-hosted machine.

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

The `/trading` room no longer polls every 5 seconds. It holds one same-origin SSE connection and updates agent status as normalized trading events arrive. The backend also exposes the equivalent WebSocket stream for future 3D-office runtime-event integration.

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
