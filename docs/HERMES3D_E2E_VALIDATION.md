# Hermes3D Phase 1.6.3 End-to-End Realtime Validation

Phase 1.6.3 adds an isolated validation harness for the realtime observability path.

The validator proves this chain without touching live trading files or Binance:

```text
synthetic test log
      -> Hermes3D read-only sidecar
      -> temporary hermes3d event journal
      -> Hermes3D realtime stream
      -> read-only state projection
```

It validates the normalized event types:

- `BUY_READY`
- `SHORT_READY`
- `RISK_PASS`
- `ORDER_OPEN`
- `TP_HIT`
- `SL_HIT`
- `CIRCUIT_BREAKER`

It also verifies that the final projection remains `read_only: true` and `trade_execution: false`.

## Safety

The validator uses `tempfile.TemporaryDirectory`. It does not read or write production `spot-long.log`, `futures-short.log`, `state/*.json`, Binance credentials, exchange clients, or order execution paths.

## Run

From the repository root:

```bash
PYTHONPATH=. python scripts/validate_hermes3d_realtime.py
```

A successful run exits with code 0 and prints an event named `HERMES3D_E2E_VALIDATION` with `passed: true`.

This test is also executed by pytest through `tests/test_hermes3d_validation.py`.
