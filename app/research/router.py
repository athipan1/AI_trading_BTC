from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.monitoring.position_store import PositionStore
from app.research.trade_dataset import ResearchTradeDatasetProjection


def build_research_router(
    *,
    spot_position_store: PositionStore,
    futures_position_store: PositionStore,
) -> APIRouter:
    router = APIRouter(prefix="/research", tags=["research"])

    def positions() -> list[dict[str, object]]:
        return spot_position_store.load() + futures_position_store.load()

    @router.get("/trades")
    def research_trades(
        strategy: str | None = Query(default=None),
        regime: str | None = Query(default=None),
    ) -> dict[str, object]:
        return ResearchTradeDatasetProjection.build(
            positions(),
            strategy_id=strategy,
            regime=regime,
        )

    @router.get("/trades.csv")
    def research_trades_csv(
        strategy: str | None = Query(default=None),
        regime: str | None = Query(default=None),
    ) -> Response:
        dataset = ResearchTradeDatasetProjection.build(
            positions(),
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

    return router
