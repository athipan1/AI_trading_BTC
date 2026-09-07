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
        validation_position_store: PositionStore | None = None,
    ) -> None:
        self.base_projection = base_projection
        self.spot_position_store = spot_position_store
        self.futures_position_store = futures_position_store
        self.validation_position_store = validation_position_store

    def analytics(self) -> dict[str, Any]:
        payload = dict(self.base_projection.analytics())
        positions = self.spot_position_store.load() + self.futures_position_store.load()
        quant = {
            "portfolio": QuantPerformanceProjection.summarize(positions),
            "strategies": QuantPerformanceProjection.by_strategy(positions),
            "market_regimes": QuantPerformanceProjection.by_market_regime(positions),
            "strategy_market_regimes": QuantPerformanceProjection.by_strategy_and_market_regime(
                positions
            ),
            "data_quality": QuantPerformanceProjection.data_availability(positions),
        }
        if self.validation_position_store is not None:
            validation_positions = self.validation_position_store.load()
            quant["validation"] = {
                "isolated": True,
                "portfolio": QuantPerformanceProjection.summarize(validation_positions),
                "market_regimes": QuantPerformanceProjection.by_market_regime(validation_positions),
                "data_quality": QuantPerformanceProjection.data_availability(validation_positions),
            }
        payload["quant_performance"] = quant
        return payload
