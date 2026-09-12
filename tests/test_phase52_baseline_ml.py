from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.research.baseline_ml import BaselineMLResearch
from app.research.entry_features import ADVANCED_ENTRY_NUMERIC_FEATURES, ENTRY_FEATURE_SCHEMA_VERSION


def _historical_trade(index: int) -> dict[str, object]:
    opened = datetime(2021, 1, 1, tzinfo=UTC) + timedelta(hours=index * 6)
    closed = opened + timedelta(hours=2)
    is_win = index % 4 == 0
    realized_r = 1.5 if is_win else -1.0
    side = "buy" if index % 2 == 0 else "sell"
    strategy = "triple_ema" if side == "buy" else "triple_ema_short"
    entry_price = 30_000.0 + index * 10.0
    exit_price = entry_price + (150.0 if is_win else -100.0) * (1 if side == "buy" else -1)
    advanced = {
        name: float(index + feature_index + 1) / 100.0
        for feature_index, name in enumerate(ADVANCED_ENTRY_NUMERIC_FEATURES)
    }
    advanced["rsi_14"] = 65.0 if is_win else 35.0
    advanced["trend_strength_atr"] = 2.0 if is_win else 0.5

    return {
        "order_id": f"hist-phase52-{index:04d}",
        "strategy_id": strategy,
        "symbol": "BTC/USDT",
        "side": side,
        "status": "CLOSED",
        "created_at": opened.isoformat(),
        "closed_at": closed.isoformat(),
        "decision_at": (opened - timedelta(hours=1)).isoformat(),
        "entry_feature_schema_version": ENTRY_FEATURE_SCHEMA_VERSION,
        "entry_features": advanced,
        "entry_price": entry_price,
        "entry_fill_price": entry_price + (2.0 if side == "buy" else -2.0),
        "quantity": 0.001,
        "initial_stop_loss": entry_price - 100.0 if side == "buy" else entry_price + 100.0,
        "initial_risk_price_distance": 102.0,
        "initial_risk_usdt": 0.102,
        "entry_market_regime": "BULL_TREND" if side == "buy" else "BEAR_TREND",
        "trade_path_highest_price": max(entry_price, exit_price) + 20.0,
        "trade_path_lowest_price": min(entry_price, exit_price) - 20.0,
        "trade_path_observation_count": 3,
        "exit_reason": "STRATEGY_EXIT",
        "exit_price": exit_price,
        "exit_fill_price": exit_price - (2.0 if side == "buy" else -2.0),
        "holding_seconds": 7200.0,
        "mae_usdt": 0.05,
        "mfe_usdt": 0.20,
        "mae_r": 0.5,
        "mfe_r": 2.0,
        "gross_realized_pnl": realized_r * 0.102,
        "net_realized_pnl": realized_r * 0.102,
        "realized_r": realized_r,
        "entry_commission_usdt": 0.01,
        "exit_commission_usdt": 0.01,
        "total_commission_usdt": 0.02,
        "mfe_capture_ratio": 0.75 if is_win else -0.5,
        "profit_giveback_r": 0.5,
        "mae_utilization_r": 0.5,
        "trade_diagnostic": "WIN" if is_win else "LOSS",
    }


def test_phase52_baseline_ml_is_research_only_and_chronological() -> None:
    historical = [_historical_trade(index) for index in range(80)]

    report = BaselineMLResearch().run(historical)

    assert report["schema_version"] == "baseline_ml_schema_v1"
    assert report["phase"] == "5.2"
    assert report["research_only"] is True
    assert report["production_position_store_mutated"] is False
    assert report["split"]["method"] == "chronological_holdout"
    assert report["split"]["random_shuffle"] is False
    assert report["split"]["checks"] == {
        "order_id_overlap": "PASS",
        "chronological_order": "PASS",
    }
    assert report["preprocessing"]["fit_scope"] == "train_only"


def test_phase52_baseline_ml_generates_probability_and_trading_metrics() -> None:
    historical = [_historical_trade(index) for index in range(80)]

    report = BaselineMLResearch().run(historical)

    assert "dummy_prior" in report["models"]
    assert "logistic_regression" in report["models"]
    assert report["selection"]["model"] == "logistic_regression"
    assert 0.30 <= report["selection"]["selected_threshold"] <= 0.80
    assert report["models"]["logistic_regression"]["validation"]["pr_auc"] is not None
    assert report["models"]["logistic_regression"]["test"]["roc_auc"] is not None
    assert report["trading_comparison"]["validation"]["rule_based_all_signals"][
        "selected_trades"
    ] == 12
    assert report["trading_comparison"]["test"]["rule_based_all_signals"][
        "selected_trades"
    ] == 12
    assert all(report["acceptance"].values())
