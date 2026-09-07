from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models import Candle
from app.monitoring.position_store import PositionStore
from app.monitoring.trade_path_observer import TradePathObserver
from app.strategies.baseline import BaselineStrategy

PHASE41_CONFIRMATION_TOKEN = "PHASE41_TESTNET_TRADE"
PHASE41_STRATEGY_ID = "phase41_validation"


class SpotValidationBroker(Protocol):
    def preflight(self, symbol: str) -> dict[str, Any]: ...

    def fetch_closed_candles(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 120,
    ) -> list[Candle]: ...

    def place_market_order(self, symbol: str, side: str, notional_usdt: float) -> dict[str, Any]: ...

    def place_market_sell_quantity(self, symbol: str, quantity: float) -> dict[str, Any]: ...

    def current_price(self, symbol: str) -> float: ...


class FillReconciler(Protocol):
    def reconcile_all(self) -> dict[str, Any]: ...


class Phase41ValidationRequest(BaseModel):
    confirm: str


class Phase41ValidationTradeService:
    """Isolated Binance Spot Testnet trade used only to validate Phase 4.1 telemetry."""

    def __init__(
        self,
        *,
        broker: SpotValidationBroker,
        position_store: PositionStore,
        trade_path_observer: TradePathObserver,
        reconciler: FillReconciler,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        notional_usdt: float = 10.0,
        stop_loss_pct: float = 0.01,
        take_profit_pct: float = 0.02,
    ) -> None:
        if not 0 < notional_usdt <= 25:
            raise ValueError("Phase 4.1 validation notional must be in (0, 25] USDT")
        if not 0 < stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be between 0 and 1")
        if not 0 < take_profit_pct < 1:
            raise ValueError("take_profit_pct must be between 0 and 1")
        self.broker = broker
        self.position_store = position_store
        self.trade_path_observer = trade_path_observer
        self.reconciler = reconciler
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.notional_usdt = float(notional_usdt)
        self.stop_loss_pct = float(stop_loss_pct)
        self.take_profit_pct = float(take_profit_pct)
        self.strategy = BaselineStrategy()

    @staticmethod
    def _confirm(token: str) -> None:
        if token != PHASE41_CONFIRMATION_TOKEN:
            raise PermissionError("invalid Phase 4.1 validation confirmation token")

    def _assert_testnet(self) -> dict[str, Any]:
        preflight = self.broker.preflight(self.symbol)
        if (
            preflight.get("mode") != "binance_spot_testnet"
            or preflight.get("sandbox") is not True
            or preflight.get("host") != "testnet.binance.vision"
        ):
            raise RuntimeError("Phase 4.1 validation refuses non-Binance-Spot-Testnet execution")
        return preflight

    def _open_position(self) -> dict[str, Any] | None:
        positions = self.position_store.active_positions(
            self.symbol,
            strategy_id=PHASE41_STRATEGY_ID,
        )
        if len(positions) > 1:
            raise RuntimeError("multiple Phase 4.1 validation positions detected")
        return positions[0] if positions else None

    def _position_by_order_id(self, order_id: str) -> dict[str, Any]:
        for item in self.position_store.load():
            if str(item.get("order_id")) == str(order_id):
                return item
        raise KeyError(f"unknown validation order: {order_id}")

    def entry(self, confirm: str) -> dict[str, Any]:
        self._confirm(confirm)
        preflight = self._assert_testnet()
        if self._open_position() is not None:
            raise ValueError("a Phase 4.1 validation position is already OPEN")

        candles = self.broker.fetch_closed_candles(
            self.symbol,
            interval=self.timeframe,
            limit=120,
        )
        signal = self.strategy.analyze(candles, self.symbol, self.timeframe)
        order = self.broker.place_market_order(self.symbol, "buy", self.notional_usdt)
        order_id = order.get("order_id")
        fill_price = order.get("average")
        quantity = order.get("sellable_quantity", order.get("filled"))
        if order_id is None or not fill_price or not quantity:
            raise RuntimeError("validation BUY acknowledgement is missing fill data")

        fill = float(fill_price)
        position = self.position_store.add_long_position(
            order_id=str(order_id),
            symbol=self.symbol,
            entry_price=fill,
            quantity=float(quantity),
            take_profit=fill * (1 + self.take_profit_pct),
            stop_loss=fill * (1 - self.stop_loss_pct),
            strategy_id=PHASE41_STRATEGY_ID,
            exit_mode="validation_manual",
        )
        captured = self.trade_path_observer.capture_result(
            {
                "event": "BUY_FILLED",
                "position": position,
                "signal": signal.model_dump(mode="json"),
            }
        )
        reconciliation = self.reconciler.reconcile_all()
        tracked = self._position_by_order_id(str(order_id))
        return {
            "event": "PHASE41_VALIDATION_ENTRY",
            "validation_only": True,
            "exchange": "binance_spot_testnet",
            "preflight": preflight,
            "order": order,
            "position": tracked,
            "trade_path_entry": captured,
            "reconciliation": reconciliation,
        }

    def sample(self, confirm: str) -> dict[str, Any]:
        self._confirm(confirm)
        self._assert_testnet()
        position = self._open_position()
        if position is None:
            raise ValueError("no OPEN Phase 4.1 validation position")
        price = float(self.broker.current_price(self.symbol))
        observed = self.trade_path_observer.observe_order_price(
            str(position["order_id"]),
            price,
        )
        return {
            "event": "PHASE41_VALIDATION_SAMPLE",
            "validation_only": True,
            "price": price,
            "position": observed,
        }

    def exit(self, confirm: str) -> dict[str, Any]:
        self._confirm(confirm)
        preflight = self._assert_testnet()
        position = self._open_position()
        if position is None:
            raise ValueError("no OPEN Phase 4.1 validation position")

        order = self.broker.place_market_sell_quantity(
            self.symbol,
            float(position["quantity"]),
        )
        order_id = order.get("order_id")
        exit_price = order.get("average")
        if order_id is None or not exit_price:
            raise RuntimeError("validation SELL acknowledgement is missing fill data")

        closed = self.position_store.mark_closed(
            str(position["order_id"]),
            exit_order_id=str(order_id),
            exit_reason="PHASE41_VALIDATION_EXIT",
            exit_price=float(exit_price),
        )
        self.trade_path_observer.capture_result(
            {
                "event": "POSITION_CLOSED",
                "closed_position": closed,
                "exit_order": order,
            }
        )
        reconciliation = self.reconciler.reconcile_all()
        tracked = self._position_by_order_id(str(position["order_id"]))
        return {
            "event": "PHASE41_VALIDATION_EXIT",
            "validation_only": True,
            "exchange": "binance_spot_testnet",
            "preflight": preflight,
            "order": order,
            "position": tracked,
            "reconciliation": reconciliation,
        }

    def status(self) -> dict[str, Any]:
        positions = self.position_store.load()
        return {
            "validation_only": True,
            "strategy_id": PHASE41_STRATEGY_ID,
            "positions": positions,
            "open_positions": sum(item.get("status") == "OPEN" for item in positions),
        }


def build_phase41_validation_router(
    *,
    service_factory: Callable[[], Phase41ValidationTradeService],
    enabled: bool,
) -> APIRouter:
    router = APIRouter(tags=["validation"])

    def service() -> Phase41ValidationTradeService:
        if not enabled:
            raise HTTPException(status_code=404, detail="Phase 4.1 validation trade is disabled")
        try:
            return service_factory()
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def execute(action: Callable[[Phase41ValidationTradeService], dict[str, Any]]) -> dict[str, Any]:
        try:
            return action(service())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/validation/phase41/entry")
    def validation_entry(request: Phase41ValidationRequest) -> dict[str, Any]:
        return execute(lambda value: value.entry(request.confirm))

    @router.post("/validation/phase41/sample")
    def validation_sample(request: Phase41ValidationRequest) -> dict[str, Any]:
        return execute(lambda value: value.sample(request.confirm))

    @router.post("/validation/phase41/exit")
    def validation_exit(request: Phase41ValidationRequest) -> dict[str, Any]:
        return execute(lambda value: value.exit(request.confirm))

    @router.get("/validation/phase41/status")
    def validation_status() -> dict[str, Any]:
        return service().status()

    return router
