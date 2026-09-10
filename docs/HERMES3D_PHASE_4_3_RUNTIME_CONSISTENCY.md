# Hermes3D Phase 4.3: Runtime Consistency + Event Contract Foundation

Phase 4.3 makes the repository the reproducible source of truth for the Hermes3D Trading Office and freezes the first stable event contract before deeper event-driven agent behavior is added.

## Event contract

The contract lives in `app/integrations/hermes3d/contracts.py` and validates the event envelope already emitted by `Hermes3DEventJournal`:

- `event`
- `agent_id`
- `generated_at` (timezone-aware ISO-8601)
- `payload`

Contract version `1.0` recognizes the existing events without changing the runtime wire format: `AGENT_ACTIVITY`, `BUY_READY`, `SHORT_READY`, `RISK_PASS`, `ORDER_OPEN`, `TP_HIT`, `SL_HIT`, `CIRCUIT_BREAKER`, `STATE_CHANGED`, `STATE_SNAPSHOT`, and `HEARTBEAT`.

This phase intentionally validates the existing envelope instead of adding new mandatory fields. That keeps the current projection and Hermes3D frontend backward compatible while giving the next lifecycle phase a single schema registry.

## Runtime consistency verification

Run from the `AI_trading_BTC` repository root:

```bash
python scripts/verify_hermes3d_runtime_consistency.py \
  --repo-root . \
  --runtime /root/Hermes3D-runtime
```

The verifier performs two independent checks:

1. Every repository-managed file under `deploy/hermes3d/overlay/` must exist with the same SHA-256 content in the runtime.
2. The speech UX patch is applied to a temporary copy of the runtime patch target. If the target changes, the runtime is not in the same canonical patched state that the repository generates.

The verification never runs the patcher against the live runtime target; the idempotency check operates on a temporary copy.

For environments without Node.js, the direct overlay comparison can be run with:

```bash
python scripts/verify_hermes3d_runtime_consistency.py \
  --repo-root . \
  --runtime /root/Hermes3D-runtime \
  --skip-patcher
```

A successful full verification prints:

```text
Hermes3D runtime consistency: PASS
```

Any missing or modified repository-managed runtime file returns exit code `1`. Patcher drift or a missing required runtime target raises an error and also fails verification.

## Acceptance gate

Phase 4.3 is complete when all repository tests and the pinned Hermes3D production Docker build pass, followed by a full consistency check against the deployed `/root/Hermes3D-runtime`.

After this gate, new event-driven behavior should extend the contract rather than introduce parallel event schemas.
