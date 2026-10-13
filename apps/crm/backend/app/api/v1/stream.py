"""SSE `GET /api/v1/stream`: события `message.created`, `lead.updated`, `escalation.updated`."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_broker, require
from app.security.principal import Principal
from app.services.event_broker import EventBroker

router = APIRouter(prefix="/api/v1", tags=["stream"])

KEEPALIVE_S = 20.0


@router.get("/stream", response_class=StreamingResponse)
async def stream(
    request: Request,
    _: Annotated[Principal, Depends(require("stream", "read"))],
    broker: Annotated[EventBroker, Depends(get_broker)],
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        yield "retry: 3000\n\n"
        async with broker.subscribe() as queue:
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                kind = event.get("type", "message")
                yield f"event: {kind}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)
