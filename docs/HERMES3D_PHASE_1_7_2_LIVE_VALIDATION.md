# Hermes3D Phase 1.7.2 Live Office Validation

Phase 1.7.2 validates the final read-only hop from the live Hermes3D event journal into the 3D office agent state and animation layer.

## Important distinction

Hermes3D's native `AGENT EVENT CONSOLE` counts gateway protocol `EventFrame` messages. The Phase 1.7 trading bridge intentionally does not inject trading events into the execution-capable gateway protocol. It consumes the same-origin read-only SSE endpoint and updates browser-side Hermes3D agent presentation state only.

Therefore `EVENTS 0/0` in the native gateway console is not, by itself, evidence that the trading SSE bridge is broken. The acceptance signal for Phase 1.7.2 is visible agent state/animation after a new journal event reaches `/events/stream`.

## Safety boundary

The validation emitter:

- writes only to `state/hermes3d-events.jsonl` (or an explicitly selected journal path),
- imports no Binance broker or execution client,
- sends no HTTP/WebSocket command to an exchange,
- creates no order, cancellation, or position mutation,
- tags every synthetic payload with `validation: true` and `read_only: true`,
- uses zero quantity and zero price in the synthetic `ORDER_OPEN` presentation event.

## Termux live validation

Keep the Trader, Sidecar, FastAPI runtime, Hermes3D gateway, and Office running. In a separate Termux shell:

```bash
cd ~/AI_trading_BTC
export PYTHONPATH=.
python scripts/validate_hermes3d_live_office.py \
  --event-journal state/hermes3d-events.jsonl \
  --strategy-id triple_ema \
  --interval-seconds 2
```

Expected visual sequence:

```text
BUY_READY   -> Triple EMA agent running animation
RISK_PASS   -> Risk Manager running animation
ORDER_OPEN  -> Positions running animation
```

The script prints each emitted event. Because `Hermes3DEventStream.stream()` starts at the journal's current byte offset, start the Office/FastAPI SSE connection before running the validation emitter. The new records will then be observed live without replaying historical events.

## Pipeline checks

Before running the emitter:

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/state
curl -N http://127.0.0.1:8000/events/stream
```

In another shell, run the emitter. The SSE terminal should show the validation events and a following `STATE_SNAPSHOT`.

For the same-origin Hermes3D proxy:

```bash
curl -N 'http://127.0.0.1:3000/api/trading-runtime?resource=events'
```

Run the emitter again and confirm the same validation events appear through the proxy.

## Acceptance criteria

Phase 1.7.2 passes when all of the following are true:

1. A new validation event is appended to the journal.
2. `/events/stream` emits the event live.
3. `/api/trading-runtime?resource=events` forwards it without mutation.
4. `TradingOfficeRealtimeBridge` maps it to the expected agent id.
5. The expected 3D agent visibly changes state/animation.
6. Trader execution continues independently and no Binance order is created by the validation path.

The native gateway `EVENTS` counter is a separate protocol telemetry surface. Wiring trading observability into that counter would require an explicit gateway-event adapter and should remain a separate change so the read-only boundary is reviewable.
