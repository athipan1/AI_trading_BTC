from __future__ import annotations

from app.models import Candle
from app.research.historical_diagnostics import (
    HistoricalDatasetDiagnostics,
    timeframe_to_milliseconds,
)


def _candle(index: int) -> Candle:
    price = 100.0 + index
    return Candle(
        timestamp_ms=index * 3_600_000,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=1,
    )


def _historical_trade(order_id: str, opened_at: str, regime: str) -> dict[str, object]:
    return {
        "order_id": order_id,
        "strategy_id": "triple_ema",
        "symbol": "BTC/USDT",
        "side": "buy",
        "status": "CLOSED",
        "created_at": opened_at,
        "closed_at": opened_at,
        "entry_price": 100.0,
        "entry_fill_price": 100.1,
        "quantity": 0.1,
        "initial_stop_loss": 90.0,
        "initial_risk_price_distance": 10.1,
        "initial_risk_usdt": 1.01,
        "entry_market_regime": regime,
        "exit_price": 110.0,
        "exit_fill_price": 109.9,
        "holding_seconds": 3600.0,
        "trade_path_highest_price": 112.0,
        "trade_path_lowest_price": 98.0,
        "trade_path_observation_count": 2,
        "mae_usdt": 0.21,
        "mfe_usdt": 1.19,
        "mae_r": 0.2079,
        "mfe_r": 1.1782,
        "gross_realized_pnl": 0.98,
        "net_realized_pnl": 0.95,
        "realized_r": 0.9406,
        "entry_commission_usdt": 0.01,
        "exit_commission_usdt": 0.01,
        "total_commission_usdt": 0.02,
        "mfe_capture_ratio": 0.7983,
        "profit_giveback_r": 0.2376,
        "mae_utilization_r": 0.2079,
        "data_origin": "historical_replay",
    }


def test_timeframe_to_milliseconds_supports_research_intervals() -> None:
    assert timeframe_to_milliseconds("1m") == 60_000
    assert timeframe_to_milliseconds("1h") == 3_600_000
    assert timeframe_to_milliseconds("1d") == 86_400_000


def test_candle_continuity_reports_gap_without_hiding_it() -> None:
    candles = [_candle(1), _candle(2), _candle(4)]

    result = HistoricalDatasetDiagnostics.candle_continuity(candles, "1h")

    assert result["status"] == "WARN"
    assert result["gap_count"] == 1
    assert result["missing_intervals"] == 1
    assert result["duplicate_timestamps"] == 0
    assert result["out_of_order_timestamps"] == 0


def test_multiyear_diagnostics_report_year_regime_and_ready_split() -> None:
    candles = [_candle(index) for index in range(1, 40)]
    trades = [
        _historical_trade(
            f"hist-{index:02d}",
            f"{2024 + (index % 3)}-01-{(index % 28) + 1:02d}T00:00:00+00:00",
            "BULL_TREND" if index % 2 == 0 else "BEAR_TREND",
        )
        for index in range(30)
    ]

    result = HistoricalDatasetDiagnostics.build(
        candles=candles,
        trades=trades,
        timeframe="1h",
    )

    assert result["candle_continuity"]["status"] == "PASS"
    assert result["trade_coverage"]["sample_size"] == 30
    assert result["trade_coverage"]["duplicate_order_ids"] == 0
    assert set(result["trade_coverage"]["years"]) == {"2024", "2025", "2026"}
    assert result["trade_coverage"]["market_regimes"] == {
        "BEAR_TREND": 15,
        "BULL_TREND": 15,
    }
    assert result["feature_quality"]["quality"]["leakage_check"]["status"] == "PASS"
    assert result["feature_quality"]["readiness"]["training"] == "READY"
    assert result["temporal_split"]["sample_size"] == 30
    assert result["temporal_split"]["random_shuffle"] is False
    assert result["temporal_split"]["readiness"] == "READY"
