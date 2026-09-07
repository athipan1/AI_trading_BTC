from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.integrations.hermes3d.quant_analytics import Hermes3DQuantAnalyticsProjection
from app.models import Candle
from app.monitoring.position_store import PositionStore
from app.monitoring.trade_path_observer import TradePathObserver
from app.validation.phase41_trade import (
    PHASE41_CONFIRMATION_TOKEN,
    Phase41ValidationTradeService,
)


class FakeBroker:
    def __init__(self) -> None:
        self.buy_calls = 0
        self.sell_calls = 0
        self.price = 102.0

    def preflight(self, symbol: str) -> dict[str, Any]:
        return {
            "mode": "binance_spot_testnet",
            "sandbox": True,
            "host": "testnet.binance.vision",
            "symbol": symbol,
            "order_sent": False,
        }

    def fetch_closed_candles(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 120,
    ) -> list[Candle]:
        del symbol, interval
        return [
            Candle(
                timestamp_ms=index * 3_600_000,
                open=100.0 + index * 0.1,
                high=101.0 + index * 0.1,
                low=99.0 + index * 0.1,
                close=100.5 + index * 0.1,
                volume=10.0,
            )
            for index in range(limit)
        ]

    def place_market_order(self, symbol: str, side: str, notional_usdt: float) -> dict[str, Any]:
        del symbol, notional_usdt
        assert side == "buy"
        self.buy_calls += 1
        return {
            "order_id": 9001,
            "average": 100.0,
            "filled": 0.1,
            "sellable_quantity": 0.1,
            "mode": "binance_spot_testnet",
            "sandbox": True,
        }

    def place_market_sell_quantity(self, symbol: str, quantity: float) -> dict[str, Any]:
        del symbol
        assert quantity == pytest.approx(0.1)
        self.sell_calls += 1
        return {
            "order_id": 9002,
            "average": 103.0,
            "filled": 0.1,
            "mode": "binance_spot_testnet",
            "sandbox": True,
        }

    def current_price(self, symbol: str) -> float:
        del symbol
        return self.price


class FakeReconciler:
    def __init__(self) -> None:
        self.calls = 0

    def reconcile_all(self) -> dict[str, Any]:
        self.calls += 1
        return {"reconciled": 1, "pending": 0, "errors": []}


class DummyAnalytics:
    def analytics(self) -> dict[str, Any]:
        return {"read_only": True}


def build_service(tmp_path: Path) -> tuple[Phase41ValidationTradeService, FakeBroker, PositionStore]:
    store = PositionStore(tmp_path / "phase41-validation.json")
    broker = FakeBroker()
    service = Phase41ValidationTradeService(
        broker=broker,
        position_store=store,
        trade_path_observer=TradePathObserver(store),
        reconciler=FakeReconciler(),
        notional_usdt=10.0,
    )
    return service, broker, store


def test_validation_trade_captures_entry_path_and_exit(tmp_path: Path) -> None:
    service, broker, store = build_service(tmp_path)

    entry = service.entry(PHASE41_CONFIRMATION_TOKEN)
    tracked = entry["position"]
    assert broker.buy_calls == 1
    assert tracked["status"] == "OPEN"
    assert tracked["strategy_id"] == "phase41_validation"
    assert tracked["initial_stop_loss"] == pytest.approx(99.0)
    assert tracked["initial_stop_loss_source"] == "entry_snapshot"
    assert tracked["entry_market_regime"]
    assert tracked["trade_path_highest_price"] == pytest.approx(100.0)
    assert tracked["trade_path_lowest_price"] == pytest.approx(100.0)

    sampled = service.sample(PHASE41_CONFIRMATION_TOKEN)
    assert sampled["position"]["trade_path_highest_price"] == pytest.approx(102.0)
    assert sampled["position"]["trade_path_observation_count"] == 1

    exited = service.exit(PHASE41_CONFIRMATION_TOKEN)
    assert broker.sell_calls == 1
    assert exited["position"]["status"] == "CLOSED"
    assert exited["position"]["trade_path_highest_price"] == pytest.approx(103.0)
    assert len(store.active_positions()) == 0


def test_validation_trade_requires_explicit_confirmation(tmp_path: Path) -> None:
    service, broker, _ = build_service(tmp_path)

    with pytest.raises(PermissionError):
        service.entry("WRONG")

    assert broker.buy_calls == 0


def test_validation_trade_refuses_non_testnet_preflight(tmp_path: Path) -> None:
    service, broker, _ = build_service(tmp_path)
    broker.preflight = lambda symbol: {
        "mode": "live",
        "sandbox": False,
        "host": "api.binance.com",
        "symbol": symbol,
    }

    with pytest.raises(RuntimeError, match="refuses non-Binance-Spot-Testnet"):
        service.entry(PHASE41_CONFIRMATION_TOKEN)

    assert broker.buy_calls == 0


def test_validation_analytics_are_isolated_from_production(tmp_path: Path) -> None:
    spot = PositionStore(tmp_path / "spot.json")
    futures = PositionStore(tmp_path / "futures.json")
    validation = PositionStore(tmp_path / "validation.json")
    validation.add_long_position(
        order_id="v1",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=1.0,
        take_profit=102.0,
        stop_loss=99.0,
        strategy_id="phase41_validation",
        exit_mode="validation_manual",
    )
    positions = validation.load()
    positions[0].update(
        {
            "status": "CLOSED",
            "exit_order_id": "v2",
            "exit_price": 103.0,
            "closed_at": "2026-09-07T00:01:00+00:00",
            "reconciliation_status": "RECONCILED",
            "entry_fill_price": 100.0,
            "entry_filled_quantity": 1.0,
            "exit_fill_price": 103.0,
            "exit_filled_quantity": 1.0,
            "gross_realized_pnl": 3.0,
            "net_realized_pnl": 3.0,
            "entry_commission_quote_equivalent": 0.0,
            "exit_commission_quote_equivalent": 0.0,
            "initial_stop_loss": 99.0,
            "initial_stop_loss_source": "entry_snapshot",
            "entry_market_regime": "BULL_TREND",
            "trade_path_highest_price": 104.0,
            "trade_path_lowest_price": 98.5,
        }
    )
    validation.save(positions)

    projection = Hermes3DQuantAnalyticsProjection(
        base_projection=DummyAnalytics(),
        spot_position_store=spot,
        futures_position_store=futures,
        validation_position_store=validation,
    )
    quant = projection.analytics()["quant_performance"]

    assert quant["portfolio"]["evaluated_trades"] == 0
    assert quant["validation"]["isolated"] is True
    assert quant["validation"]["portfolio"]["evaluated_trades"] == 1
    assert quant["validation"]["portfolio"]["mae_mfe_coverage_pct"] == 100.0
    assert quant["validation"]["data_quality"]["market_regime_available"] is True
