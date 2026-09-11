from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.monitoring.position_store import PositionStore
from app.research.router import build_research_router
from app.research.trade_dataset import ResearchTradeDatasetProjection


def _qualified_trade(
    order_id: str,
    *,
    strategy_id: str = "triple_ema_short",
    regime: str = "BEAR_TREND",
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "strategy_id": strategy_id,
        "symbol": "BTC/USDT",
        "side": "sell",
        "status": "CLOSED",
        "reconciliation_status": "RECONCILED",
        "created_at": "2026-09-10T00:00:00+00:00",
        "closed_at": "2026-09-10T01:00:00+00:00",
        "entry_price": 100.0,
        "entry_fill_price": 100.1,
        "entry_filled_quantity": 0.1,
        "quantity": 0.1,
        "stop_loss": 105.0,
        "initial_stop_loss": 110.0,
        "initial_stop_loss_source": "entry_snapshot",
        "initial_risk_price_distance": 10.0,
        "initial_risk_usdt": 1.0,
        "initial_risk_source": "entry_snapshot",
        "entry_market_regime": regime,
        "trade_path_highest_price": 104.0,
        "trade_path_lowest_price": 80.0,
        "trade_path_observation_count": 12,
        "exit_reason": "TAKE_PROFIT",
        "exit_price": 85.0,
        "exit_fill_price": 85.1,
        "exit_filled_quantity": 0.1,
        "entry_commission_quote_equivalent": 0.01,
        "exit_commission_quote_equivalent": 0.01,
        "gross_realized_pnl": 1.5,
        "net_realized_pnl": 1.48,
    }


def test_dataset_contains_only_phase47_qualified_trades() -> None:
    legacy = _qualified_trade("legacy")
    legacy["initial_stop_loss"] = None
    open_trade = _qualified_trade("open")
    open_trade["status"] = "OPEN"
    result = ResearchTradeDatasetProjection.build(
        [legacy, open_trade, _qualified_trade("qualified")]
    )

    assert result["schema_version"] == "research_trade_schema_v1"
    assert result["basis"] == "phase47_qualified_reconciled_closed_trades"
    assert result["read_only"] is True
    assert result["metadata"]["qualified_trades"] == 1
    assert result["metadata"]["excluded_candidates"] == 2
    assert result["rows"][0]["order_id"] == "qualified"
    assert result["rows"][0]["realized_r"] > 1.0
    assert result["rows"][0]["mfe_r"] > 0
    assert result["rows"][0]["mae_r"] <= 0
    assert "entry_market_regime" in result["columns"]["features"]
    assert "net_realized_pnl" in result["columns"]["targets"]


def test_dataset_filters_strategy_and_regime() -> None:
    positions = [
        _qualified_trade("short-bear"),
        _qualified_trade("short-sideways", regime="SIDEWAYS"),
        _qualified_trade("long-bull", strategy_id="triple_ema", regime="BULL_TREND"),
    ]

    result = ResearchTradeDatasetProjection.build(
        positions,
        strategy_id="TRIPLE_EMA_SHORT",
        regime="bear_trend",
    )

    assert result["metadata"]["filtered_candidates"] == 1
    assert result["metadata"]["qualified_trades"] == 1
    assert result["rows"][0]["order_id"] == "short-bear"
    assert result["filters"]["strategy_id"] == "triple_ema_short"
    assert result["filters"]["entry_market_regime"] == "BEAR_TREND"


def test_invalid_holding_period_is_excluded_with_reason() -> None:
    trade = _qualified_trade("bad-time")
    trade["closed_at"] = "2026-09-09T23:00:00+00:00"

    result = ResearchTradeDatasetProjection.build([trade])

    assert result["metadata"]["qualified_trades"] == 0
    assert result["metadata"]["exclusion_reason_counts"]["INVALID_HOLDING_PERIOD"] == 1


def test_research_router_exports_json_and_csv(tmp_path: Path) -> None:
    spot = PositionStore(tmp_path / "spot.json")
    futures = PositionStore(tmp_path / "futures.json")
    futures.save([_qualified_trade("short-bear")])

    app = FastAPI()
    app.include_router(
        build_research_router(
            spot_position_store=spot,
            futures_position_store=futures,
        )
    )
    client = TestClient(app)

    json_response = client.get("/research/trades?strategy=triple_ema_short&regime=BEAR_TREND")
    assert json_response.status_code == 200
    assert json_response.json()["metadata"]["qualified_trades"] == 1

    csv_response = client.get("/research/trades.csv?strategy=triple_ema_short")
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert len(rows) == 1
    assert rows[0]["order_id"] == "short-bear"
    assert rows[0]["entry_market_regime"] == "BEAR_TREND"
