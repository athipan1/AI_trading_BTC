from __future__ import annotations

import asyncio

from app.integrations.hermes3d.validation import validate_realtime_pipeline


def test_realtime_validation_pipeline_passes() -> None:
    result = asyncio.run(validate_realtime_pipeline())

    assert result.passed is True
    assert result.read_only is True
    assert result.trade_execution is False
    assert {
        "BUY_READY",
        "SHORT_READY",
        "RISK_PASS",
        "ORDER_OPEN",
        "TP_HIT",
        "SL_HIT",
        "CIRCUIT_BREAKER",
    }.issubset(set(result.observed_events))
    assert result.journal_records > 0
