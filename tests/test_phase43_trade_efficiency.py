from __future__ import annotations

import pytest

from app.integrations.hermes3d.trade_efficiency import TradeEfficiencyProjection


def _trade(
    *,
    order_id: str,
    strategy_id: str = "triple_ema",
    regime: str = "BULL_TREND",
    side: str = "buy",
    entry: float = 100.0,
    stop: float = 90.0,
    high: float = 120.0,
    low: float = 96.0,
    pnl: float = 1.2,
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "strategy_id": strategy_id,
        "status": "CLOSED",
        "reconciliation_status": "RECONCILED",
        "side": side,
        "entry_fill_price": entry,
        "entry_filled_quantity": 0.1,
        "initial_stop_loss": stop,
        "initial_stop_loss_source": "entry_snapshot",
        "entry_market_regime": regime,
        "trade_path_highest_price": high,
        "trade_path_lowest_price": low,
        "net_realized_pnl": pnl,
    }


def test_trade_efficiency_calculates_capture_giveback_and_good_exit() -> None:
    metrics = TradeEfficiencyProjection._trade_efficiency(
        _trade(order_id="good", pnl=1.2, high=120.0, low=96.0)
    )

    assert metrics is not None
    assert metrics["realized_r"] == pytest.approx(1.2)
    assert metrics["mfe_r"] == pytest.approx(2.0)
    assert metrics["mae_r"] == pytest.approx(-0.4)
    assert metrics["mfe_capture_ratio"] == pytest.approx(0.6)
    assert metrics["profit_giveback_r"] == pytest.approx(0.8)
    assert metrics["mae_utilization_r"] == pytest.approx(0.4)
    assert metrics["diagnostic"] == "GOOD_ENTRY_GOOD_EXIT"


def test_negative_capture_and_reversal_are_preserved() -> None:
    metrics = TradeEfficiencyProjection._trade_efficiency(
        _trade(order_id="reversal", pnl=-0.5, high=112.0, low=95.0)
    )

    assert metrics is not None
    assert metrics["mfe_r"] == pytest.approx(1.2)
    assert metrics["realized_r"] == pytest.approx(-0.5)
    assert metrics["mfe_capture_ratio"] == pytest.approx(-0.5 / 1.2)
    assert metrics["profit_giveback_r"] == pytest.approx(1.7)
    assert metrics["winner_to_loser_reversal"] is True


def test_short_trade_uses_existing_inverse_excursion_logic() -> None:
    metrics = TradeEfficiencyProjection._trade_efficiency(
        _trade(
            order_id="short",
            strategy_id="triple_ema_short",
            regime="BEAR_TREND",
            side="sell",
            entry=100.0,
            stop=110.0,
            high=105.0,
            low=80.0,
            pnl=1.4,
        )
    )

    assert metrics is not None
    assert metrics["mfe_r"] == pytest.approx(2.0)
    assert metrics["mae_r"] == pytest.approx(-0.5)
    assert metrics["mfe_capture_ratio"] == pytest.approx(0.7)
    assert metrics["diagnostic"] == "GOOD_ENTRY_GOOD_EXIT"


def test_zero_mfe_has_no_capture_ratio_and_low_opportunity_label() -> None:
    metrics = TradeEfficiencyProjection._trade_efficiency(
        _trade(order_id="flat", high=100.0, low=98.0, pnl=-0.1)
    )

    assert metrics is not None
    assert metrics["mfe_r"] == 0.0
    assert metrics["mfe_capture_ratio"] is None
    assert metrics["diagnostic"] == "LOW_OPPORTUNITY"


def test_summary_excludes_legacy_trade_path_and_reports_coverage() -> None:
    valid = _trade(order_id="valid")
    legacy = {
        "order_id": "legacy",
        "strategy_id": "baseline",
        "status": "CLOSED",
        "reconciliation_status": "RECONCILED",
        "side": "buy",
        "entry_fill_price": 100.0,
        "entry_filled_quantity": 0.1,
        "stop_loss": 90.0,
        "net_realized_pnl": 0.5,
    }

    summary = TradeEfficiencyProjection.summarize([valid, legacy])

    assert summary["reconciled_trades_seen"] == 2
    assert summary["evaluated_trades"] == 1
    assert summary["excluded_missing_trade_path"] == 1
    assert summary["trade_efficiency_coverage_pct"] == pytest.approx(50.0)
    assert summary["capture_ratio_coverage_pct"] == pytest.approx(50.0)


def test_segmentation_preserves_strategy_and_regime_boundaries() -> None:
    positions = [
        _trade(order_id="long", strategy_id="triple_ema", regime="BULL_TREND"),
        _trade(
            order_id="short",
            strategy_id="triple_ema_short",
            regime="BEAR_TREND",
            side="sell",
            entry=100.0,
            stop=110.0,
            high=105.0,
            low=80.0,
            pnl=1.0,
        ),
    ]

    matrix = TradeEfficiencyProjection.by_strategy_and_market_regime(positions)

    assert matrix["triple_ema"]["BULL_TREND"]["evaluated_trades"] == 1
    assert matrix["triple_ema_short"]["BEAR_TREND"]["evaluated_trades"] == 1
