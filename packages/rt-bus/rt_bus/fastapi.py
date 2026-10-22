"""Тонкие обёртки FastAPI/Starlette: роутер приёмника и ASGI-middleware корреляции.

app.add_middleware(CorrelationMiddleware)
app.include_router(bus_router(lambda: container.bus))   # POST /bus/v1/events
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .context import REQUEST_ID_HEADER, correlation, correlation_from_headers
from .receiver import ReceiveResult

BUS_PATH = "/bus/v1/events"


class Receiver(Protocol):
    async def receive(self, headers: Mapping[str, str], body: bytes) -> ReceiveResult: ...


def bus_router(
    receiver: Receiver | Callable[[], Receiver], *, path: str = BUS_PATH, include_in_schema: bool = False
) -> APIRouter:
    """Роутер `POST /bus/v1/events`. `receiver` — `AsyncBus`, `MemoryReceiver` или функция без аргументов."""
    router = APIRouter()

    async def receive_event(request: Request) -> JSONResponse:
        target = receiver if hasattr(receiver, "receive") else receiver()
        result = await target.receive(dict(request.headers), await request.body())
        return JSONResponse(result.body, status_code=result.status_code)

    router.add_api_route(
        path, receive_event, methods=["POST"], include_in_schema=include_in_schema, name="rt_bus_receive"
    )
    return router


class CorrelationMiddleware:
    """ASGI: контекст корреляции из `X-Request-ID` / `traceparent` (нет — новый UUID), `X-Request-ID` в ответе."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        cid, traceparent = correlation_from_headers(headers)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                if REQUEST_ID_HEADER.lower().encode() not in names:
                    message["headers"] = [*message.get("headers", []), (b"x-request-id", cid.encode())]
            await send(message)

        with correlation(cid, traceparent):
            await self.app(scope, receive, send_with_id)
