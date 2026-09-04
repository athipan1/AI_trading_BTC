from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.integrations.hermes3d.adapter import Hermes3DReadOnlyAdapter
from app.market_data.service import MarketDataError


def build_hermes3d_router(adapter: Hermes3DReadOnlyAdapter) -> APIRouter:
    router = APIRouter(tags=["hermes3d"])

    @router.get("/registry")
    def registry() -> dict[str, Any]:
        return adapter.registry()

    @router.get("/state")
    def state() -> dict[str, Any]:
        try:
            return adapter.state()
        except MarketDataError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
