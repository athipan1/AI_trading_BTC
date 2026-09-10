from __future__ import annotations

from app.integrations.hermes3d.production_analytics_readiness import (
    ProductionAnalyticsReadinessProjection,
)


def _trade(
    order_id: str,
    *,
    strategy_id: str = "triple_ema_short",
    qualified: bool = True,
    reconciled: bool = True,
) -> dict[str, object]:
    trade: dict[str, object] = {
        "order_id": order_id,
        "strategy_id": strategy_id,
        "side": "sell",
        "status": "CLOSED",
        "reconciliation_status": "RECONCILED" if reconciled else "PENDING",
        "entry_price": 100.0,
        "quantity": 0.1,
        "stop_loss": 110.0,
        "net_realized_pnl": 1.0 if reconciled else None,
    }
    if qualified:
        trade.update(
            {
                "initial_stop_loss": 110.0,
                "initial_stop_loss_source": "entry_snapshot",
                "initial_risk_price_distance": 10.0,
                "initial_risk_usdt": 1.0,
                "initial_risk_source": "entry_snapshot",
                "entry_market_regime": "BEAR_TREND",
                "trade_path_highest_price": 104.0,
                "trade_path_lowest_price": 80.0,
            }
        )
    return trade


def test_legacy_trades_are_kept_out_of_qualified_research_cohort() -> None:
    result = ProductionAnalyticsReadinessProjection.summarize(
        [_trade("legacy", qualified=False), _trade("phase42")]
    )

    assert result["closed_trades"] == 2
    assert result["reconciled_closed_trades"] == 2
    assert result["qualified_trades"] == 1
    assert result["legacy_or_unqualified_reconciled_trades"] == 1
    assert result["coverage"]["reconciliation_pct"] == 100.0
    assert result["coverage"]["qualified_cohort_pct"] == 50.0
    assert result["readiness"]["accounting"] == "READY"
    assert result["readiness"]["data_quality"] == "NOT_READY"
    assert result["readiness"]["research"] == "NOT_READY"


def test_unreconciled_closed_trade_blocks_accounting_acceptance() -> None:
    result = ProductionAnalyticsReadinessProjection.summarize(
        [_trade("good"), _trade("pending", reconciled=False)]
    )

    assert result["coverage"]["reconciliation_pct"] == 50.0
    assert result["readiness"]["accounting"] == "NOT_READY"


def test_strategy_readiness_is_independent() -> None:
    positions = [
        _trade("short", strategy_id="triple_ema_short"),
        _trade("long-legacy", strategy_id="triple_ema", qualified=False),
    ]

    result = ProductionAnalyticsReadinessProjection.by_strategy(positions)

    assert result["triple_ema_short"]["qualified_trades"] == 1
    assert result["triple_ema_short"]["readiness"]["data_quality"] == "READY"
    assert result["triple_ema"]["qualified_trades"] == 0
    assert result["triple_ema"]["readiness"]["data_quality"] == "NOT_READY"


def test_research_sample_is_separate_from_pipeline_quality() -> None:
    positions = [_trade(f"trade-{index}") for index in range(30)]
    result = ProductionAnalyticsReadinessProjection.summarize(positions)

    assert result["coverage"]["initial_risk_snapshot_pct"] == 100.0
    assert result["coverage"]["market_regime_pct"] == 100.0
    assert result["coverage"]["trade_path_mae_mfe_pct"] == 100.0
    assert result["readiness"]["data_quality"] == "READY"
    assert result["readiness"]["research_sample"] == "SUFFICIENT"
    assert result["readiness"]["research"] == "READY"
