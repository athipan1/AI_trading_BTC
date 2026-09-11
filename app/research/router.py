from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.monitoring.position_store import PositionStore
from app.research.feature_dataset import ResearchFeatureDatasetProjection
from app.research.historical_report import HistoricalDiagnosticsReport
from app.research.historical_store import HistoricalResearchStore
from app.research.trade_dataset import ResearchSource, ResearchTradeDatasetProjection


def build_research_router(
    *,
    spot_position_store: PositionStore,
    futures_position_store: PositionStore,
    historical_trade_store: HistoricalResearchStore | None = None,
    historical_diagnostics_report: HistoricalDiagnosticsReport | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/research", tags=["research"])

    def positions() -> list[dict[str, object]]:
        return spot_position_store.load() + futures_position_store.load()

    def historical_trades() -> list[dict[str, object]]:
        if historical_trade_store is None:
            return []
        return historical_trade_store.load()

    @router.get("/trades")
    def research_trades(
        source: ResearchSource = "production",
        strategy: str | None = Query(default=None),
        regime: str | None = Query(default=None),
    ) -> dict[str, object]:
        return ResearchTradeDatasetProjection.build(
            positions(),
            historical_trades=historical_trades(),
            source=source,
            strategy_id=strategy,
            regime=regime,
        )

    @router.get("/trades.csv")
    def research_trades_csv(
        source: ResearchSource = "production",
        strategy: str | None = Query(default=None),
        regime: str | None = Query(default=None),
    ) -> Response:
        dataset = ResearchTradeDatasetProjection.build(
            positions(),
            historical_trades=historical_trades(),
            source=source,
            strategy_id=strategy,
            regime=regime,
        )
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(ResearchTradeDatasetProjection.COLUMNS))
        writer.writeheader()
        for row in dataset["rows"]:
            writer.writerow(row)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{ResearchTradeDatasetProjection.SCHEMA_VERSION}.csv"'
                )
            },
        )

    @router.get("/features")
    def research_features(
        source: ResearchSource = "production",
        strategy: str | None = Query(default=None),
        regime: str | None = Query(default=None),
    ) -> dict[str, object]:
        return ResearchFeatureDatasetProjection.build(
            positions(),
            historical_trades=historical_trades(),
            source=source,
            strategy_id=strategy,
            regime=regime,
        )

    @router.get("/dataset-quality")
    def research_dataset_quality(
        source: ResearchSource = "production",
        strategy: str | None = Query(default=None),
        regime: str | None = Query(default=None),
    ) -> dict[str, object]:
        return ResearchFeatureDatasetProjection.quality(
            positions(),
            historical_trades=historical_trades(),
            source=source,
            strategy_id=strategy,
            regime=regime,
        )

    @router.get("/dataset-split")
    def research_dataset_split(
        source: ResearchSource = "production",
        strategy: str | None = Query(default=None),
        regime: str | None = Query(default=None),
    ) -> dict[str, object]:
        return ResearchFeatureDatasetProjection.temporal_split(
            positions(),
            historical_trades=historical_trades(),
            source=source,
            strategy_id=strategy,
            regime=regime,
        )

    @router.get("/historical-diagnostics")
    def historical_diagnostics() -> dict[str, object]:
        if historical_diagnostics_report is None:
            return {
                "schema_version": "historical_dataset_diagnostics_v1",
                "status": "NOT_CONFIGURED",
            }
        return historical_diagnostics_report.load()

    return router
