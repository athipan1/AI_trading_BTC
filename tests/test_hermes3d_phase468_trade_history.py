from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.integrations.hermes3d.router import build_hermes3d_router
from app.integrations.hermes3d.trade_history import Hermes3DTradeHistoryProjection
from app.monitoring.position_store import PositionStore


class StubRuntime:
    def registry(self) -> dict:
        return {}

    def state(self) -> dict:
        return {}


def build_history(tmp_path: Path) -> Hermes3DTradeHistoryProjection:
    return Hermes3DTradeHistoryProjection(
        spot_position_store=PositionStore(tmp_path / "spot.json"),
        futures_position_store=PositionStore(tmp_path / "futures.json"),
    )


def test_history_projects_closed_long_and_short_without_mutation(tmp_path: Path) -> None:
    projection = build_history(tmp_path)
    spot = projection.spot_position_store
    futures = projection.futures_position_store

    spot.add_long_position(
        order_id="long-1",
        symbol="BTC/USDT",
        entry_price=100,
        quantity=0.1,
        take_profit=120,
        stop_loss=90,
        strategy_id="baseline",
    )
    spot.mark_closed("long-1", exit_order_id="long-exit", exit_reason="TP_HIT", exit_price=120)

    futures.add_short_position(
        order_id="short-1",
        symbol="BTC/USDT",
        entry_price=200,
        quantity=0.1,
        take_profit=180,
        stop_loss=210,
        strategy_id="triple_ema_short",
    )
    futures.mark_closed("short-1", exit_order_id="short-exit", exit_reason="TP_HIT", exit_price=180)

    before_spot = spot.path.read_text(encoding="utf-8")
    before_futures = futures.path.read_text(encoding="utf-8")
    payload = projection.history()

    assert payload["read_only"] is True
    assert payload["source"] == "production_position_stores"
    assert payload["summary"]["closed_trades"] == 2
    assert payload["summary"]["winning_trades"] == 2
    assert payload["summary"]["realized_pnl_usdt"] == pytest.approx(4.0)
    assert {trade["side"] for trade in payload["trades"]} == {"LONG", "SHORT"}
    assert spot.path.read_text(encoding="utf-8") == before_spot
    assert futures.path.read_text(encoding="utf-8") == before_futures


def test_history_endpoint_is_read_only_projection(tmp_path: Path) -> None:
    projection = build_history(tmp_path)
    app = FastAPI()
    app.include_router(build_hermes3d_router(StubRuntime(), trade_history_reader=projection))
    response = TestClient(app).get("/history")

    assert response.status_code == 200
    assert response.json()["read_only"] is True
    assert response.json()["trades"] == []


def test_office_overlay_mounts_history_and_proxy_is_allowlisted() -> None:
    root = Path(__file__).resolve().parents[1]
    office = (root / "deploy/hermes3d/overlay/src/app/office/page.tsx").read_text(encoding="utf-8")
    proxy = (
        root / "deploy/hermes3d/overlay/src/app/api/trading-runtime/route.ts"
    ).read_text(encoding="utf-8")
    panel = (
        root / "deploy/hermes3d/overlay/src/features/trading/TradingHistoryPanel.tsx"
    ).read_text(encoding="utf-8")

    assert "<TradingHistoryPanel />" in office
    assert '"history"' in proxy
    assert 'resource=history' in panel
    assert "Production PositionStore" in panel
    assert "data-trading-history-drawer" in panel
