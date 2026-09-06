from __future__ import annotations

from typing import Any, Protocol

from app.integrations.hermes3d.quant_performance import QuantPerformanceProjection
from app.monitoring.position_store import PositionStore


class AnalyticsReader(Protocol):
    def analytics(self) -> dict[str, Any]:
        ...


class Hermes3DQuantAnalyticsProjection:
    """Decorate the existing analytics projection with reconciled quant metrics."""

    def __init__(
        self,
        *,
        base_projection: AnalyticsReader,
        spot_position_store: PositionStore,
        futures_position_store: PositionStore,
    ) -> None:
        self.base_projection = base_projection
        self.spot_position_store = spot_position_store
        self.futures_position_store = futures_position_store

    def analytics(self) -> dict[str, Any]:
        payload = dict(self.base_projection.analytics())
        positions = self.spot_position_store.load() + self.futures_position_store.load()
        payload["quant_performance"] = {
            "portfolio": QuantPerformanceProjection.summarize(positions),
            "strategies": QuantPerformanceProjection.by_strategy(positions),
            "data_quality": {
                "advanced_metrics_basis": "exchange_reconciled_closed_trades_only",
                "mae_mfe_available": False,
                "mae_mfe_reason": "intratrade_extrema_not_persisted",
                "market_regime_available": False,
                "market_regime_reason": "entry_regime_not_persisted",
            },
        }
        return payload
