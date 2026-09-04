from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.integrations.hermes3d.events import Hermes3DEventStream


class Hermes3DRuntimeReader(Protocol):
    def registry(self) -> dict[str, Any]: ...

    def state(self) -> dict[str, Any]: ...


def build_hermes3d_router(
    reader: Hermes3DRuntimeReader,
    event_stream: Hermes3DEventStream | None = None,
) -> APIRouter:
    router = APIRouter(tags=["hermes3d"])

    @router.get("/registry")
    def registry() -> dict[str, Any]:
        return reader.registry()

    @router.get("/state")
    def state() -> dict[str, Any]:
        return reader.state()

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
