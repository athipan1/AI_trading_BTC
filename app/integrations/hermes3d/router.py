from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.integrations.hermes3d.events import Hermes3DEventStream


class Hermes3DRuntimeReader(Protocol):
    def registry(self) -> dict[str, Any]: ...

    def state(self) -> dict[str, Any]: ...


class Hermes3DAnalyticsReader(Protocol):
    def analytics(self) -> dict[str, Any]: ...


class Hermes3DValidationSimulator(Protocol):
    @classmethod
    def allowed_events(cls) -> tuple[str, ...]: ...

    def publish(self, event_name: str) -> dict[str, Any]: ...


def build_hermes3d_router(
    reader: Hermes3DRuntimeReader,
    event_stream: Hermes3DEventStream | None = None,
    analytics_reader: Hermes3DAnalyticsReader | None = None,
    validation_simulator: Hermes3DValidationSimulator | None = None,
    validation_simulator_enabled: bool = False,
) -> APIRouter:
    router = APIRouter(tags=["hermes3d"])

    @router.get("/registry")
    def registry() -> dict[str, Any]:
        return reader.registry()

    @router.get("/state")
    def state() -> dict[str, Any]:
        payload = reader.state()
        if "trade_lifecycle" not in payload and "lifecycle" in payload:
            payload = dict(payload)
            payload["trade_lifecycle"] = payload["lifecycle"]

        lifecycle = payload.get("trade_lifecycle")
        if isinstance(lifecycle, dict):
            payload = dict(payload)
            payload.setdefault("active_trade", lifecycle.get("active_trade"))
            payload.setdefault("trade_lifecycles", lifecycle.get("trade_lifecycles", {}))
        return payload

    if analytics_reader is not None:

        @router.get("/analytics")
        def analytics() -> dict[str, Any]:
            return analytics_reader.analytics()

    if validation_simulator is not None:

        @router.post("/validation/events/{event_name}")
        def publish_validation_event(event_name: str) -> dict[str, Any]:
            if not validation_simulator_enabled:
                raise HTTPException(status_code=404, detail="Hermes3D validation simulator is disabled")
            normalized = event_name.strip().upper()
            if normalized not in validation_simulator.allowed_events():
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Unsupported Hermes3D validation event",
                        "allowed_events": list(validation_simulator.allowed_events()),
                    },
                )
            record = validation_simulator.publish(normalized)
            return {
                "published": True,
                "read_only": True,
                "trade_execution": False,
                "event": record,
            }

    if event_stream is not None:

        async def sse_events() -> AsyncIterator[str]:
            try:
                async for event in event_stream.stream():
                    yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
            except asyncio.CancelledError:
                return
            except Exception as exc:
                error = {
                    "event": "STREAM_ERROR",
                    "agent_id": "market-data",
                    "payload": {"error": f"{exc.__class__.__name__}: {exc}"},
                }
                yield f"data: {json.dumps(error, separators=(',', ':'))}\n\n"

        @router.get("/events/stream")
        async def events_stream() -> StreamingResponse:
            return StreamingResponse(
                sse_events(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        @router.websocket("/events/ws")
        async def events_websocket(websocket: WebSocket) -> None:
            await websocket.accept()
            try:
                async for event in event_stream.stream():
                    await websocket.send_json(event)
            except WebSocketDisconnect:
                return
            except Exception as exc:
                await websocket.send_json(
                    {
                        "event": "STREAM_ERROR",
                        "agent_id": "market-data",
                        "payload": {"error": f"{exc.__class__.__name__}: {exc}"},
                    }
                )
                await websocket.close(code=1011)

    return router
