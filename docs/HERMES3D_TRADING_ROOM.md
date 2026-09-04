# Hermes3D Trading Room

Phase 1.5 runs the real Hermes3D Studio against the AI Trading BTC FastAPI runtime through Hermes3D's `custom` runtime seam.

## Safety boundary

This integration is read-only.

Hermes3D can read only:

- `GET /health`
- `GET /registry`
- `GET /state`

The Trading Room proxy exports only HTTP `GET` and whitelists those three resources. It has no route for order placement, order cancellation, position modification, or execution.

The AI Trading BTC `/state` payload also reports:

- `trade_execution: false`
- `order_cancel: false`
- `position_modify: false`
- `risk.execution_enabled: false`

## Start

From the repository root:

```bash
docker compose -f docker-compose.yml -f docker-compose.hermes3d.yml up --build
```

Services:

- AI Trading BTC API: `http://localhost:8000`
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

Hermes3D reads the `active` map from `/state` and materializes these observer agents in the office:

- `market-data`
- `baseline`
- `triple_ema`
- `triple_ema_short`
- `risk-manager`
- `positions`

The `/trading` room polls `/state` and `/registry` every 5 seconds and displays the richer `agent_statuses` projection for those same agents.

## Hermes3D source pin

The integration image builds from upstream `iamlukethedev/Hermes3D` at the pinned commit declared by `HERMES3D_REF` in `deploy/hermes3d/Dockerfile`.

Pinning avoids an upstream change silently breaking the production trading stack. Upgrade the pin deliberately and validate the Docker build before merging.

## Stop

```bash
docker compose -f docker-compose.yml -f docker-compose.hermes3d.yml down
```
