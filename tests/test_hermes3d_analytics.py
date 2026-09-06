from __future__ import annotations

from pathlib import Path

import pytest

from app.auto_trading.state_store import AutoTradeStateStore
from app.integrations.hermes3d.analytics import Hermes3DTradingAnalyticsProjection
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.monitoring.position_store import PositionStore


def build_analytics(tmp_path: Path) -> Hermes3DTradingAnalyticsProjection:
    return Hermes3DTradingAnalyticsProjection(
        journal=Hermes3DEventJournal(tmp_path / "events.jsonl"),
        spot_position_store=PositionStore(tmp_path / "spot.json"),
        futures_position_store=PositionStore(tmp_path / "futures.json"),
        auto_state_paths={
            "baseline": tmp_path / "baseline-state.json",
            "triple_ema": tmp_path / "triple-ema-state.json",
            "triple_ema_short": tmp_path / "short-state.json",
        },
    )


def test_empty_analytics_is_read_only_and_zeroed(tmp_path: Path) -> None:
    analytics = build_analytics(tmp_path).analytics()

    assert analytics["read_only"] is True
    assert analytics["portfolio"]["open_positions"] == 0
    assert analytics["portfolio"]["closed_trades"] == 0
    assert analytics["portfolio"]["win_rate_pct"] == 0.0
    assert analytics["portfolio"]["profit_factor"] is None
    assert analytics["execution"] == {"tp_count": 0, "sl_count": 0}
    assert analytics["risk"]["circuit_breaker_active"] is False
    assert analytics["data_quality"]["pnl_basis"] == "entry_exit_estimate"
    assert analytics["data_quality"]["fees_included"] is False


def test_analytics_aggregates_long_short_and_strategy_metrics(tmp_path: Path) -> None:
    projection = build_analytics(tmp_path)
    spot = projection.spot_position_store
    futures = projection.futures_position_store

    spot.add_long_position(
        order_id="long-win",
        symbol="BTC/USDT",
        entry_price=100,
        quantity=0.1,
        take_profit=120,
        stop_loss=90,
        strategy_id="baseline",
    )
    spot.mark_closed(
        "long-win",
        exit_order_id="exit-long-win",
        exit_reason="TP_HIT",
        exit_price=120,
    )

    spot.add_long_position(
        order_id="long-loss",
        symbol="BTC/USDT",
        entry_price=100,
        quantity=0.1,
        take_profit=120,
        stop_loss=90,
        strategy_id="triple_ema",
    )
    spot.mark_closed(
        "long-loss",
        exit_order_id="exit-long-loss",
        exit_reason="SL_HIT",
        exit_price=90,
    )

    futures.add_short_position(
        order_id="short-win",
        symbol="BTC/USDT",
        entry_price=200,
        quantity=0.1,
        take_profit=180,
        stop_loss=210,
        strategy_id="triple_ema_short",
    )
    futures.mark_closed(
        "short-win",
        exit_order_id="exit-short-win",
        exit_reason="TP_HIT",
        exit_price=180,
    )

    spot.add_long_position(
        order_id="open-long",
        symbol="BTC/USDT",
        entry_price=110,
        quantity=0.1,
        take_profit=130,
        stop_loss=100,
        strategy_id="baseline",
    )

    analytics = projection.analytics()
    portfolio = analytics["portfolio"]

    assert portfolio["open_positions"] == 1
    assert portfolio["closed_trades"] == 3
    assert portfolio["winning_trades"] == 2
    assert portfolio["losing_trades"] == 1
    assert portfolio["win_rate_pct"] == pytest.approx(66.6667)
    assert portfolio["estimated_realized_pnl_usdt"] == pytest.approx(3.0)
    assert portfolio["gross_profit_usdt"] == pytest.approx(4.0)
    assert portfolio["gross_loss_usdt"] == pytest.approx(-1.0)
    assert portfolio["profit_factor"] == pytest.approx(4.0)
    assert analytics["execution"] == {"tp_count": 2, "sl_count": 1}

    assert analytics["strategies"]["baseline"]["open_positions"] == 1
    assert analytics["strategies"]["baseline"]["estimated_realized_pnl_usdt"] == pytest.approx(2.0)
    assert analytics["strategies"]["triple_ema"]["estimated_realized_pnl_usdt"] == pytest.approx(-1.0)
    assert analytics["strategies"]["triple_ema_short"]["estimated_realized_pnl_usdt"] == pytest.approx(2.0)


def test_analytics_projects_risk_events_and_current_circuit_breaker(tmp_path: Path) -> None:
    projection = build_analytics(tmp_path)
    projection.journal.publish(
        event="RISK_PASS",
        agent_id="risk-manager",
        payload={"strategy_id": "baseline"},
    )
    projection.journal.publish(
        event="RISK_PASS",
        agent_id="risk-manager",
        payload={"strategy_id": "triple_ema"},
    )
    projection.journal.publish_circuit_breaker(
        strategy_id="triple_ema_short",
        reason="test breaker",
    )
    AutoTradeStateStore(projection.auto_state_paths["triple_ema_short"]).halt("test breaker")

    risk = projection.analytics()["risk"]

    assert risk["risk_pass_count"] == 2
    assert risk["circuit_breaker_event_count"] == 1
    assert risk["circuit_breaker_active"] is True
    assert risk["halted_strategies"]["triple_ema_short"]["reason"] == "test breaker"
