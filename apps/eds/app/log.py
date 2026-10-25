"""Структурные логи: JSON в stdout для приложения и сторонних библиотек (uvicorn, alembic, procrastinate).

`request_id` — это `X-Request-ID` запроса (`rt_bus.fastapi.CorrelationMiddleware`), он же `correlationid`
событий, опубликованных при обработке запроса. Логировать только kwargs, без f-строк; секретов и токенов в
записях быть не должно.
"""

import logging
import sys
import time
from typing import Any

import structlog
from rt_bus import get_correlation_id
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.types import EventDict, Processor, WrappedLogger

from app.config import Settings

_HANDLER_NAME = "structlog-stdout"
# Библиотеки на INFO печатают URL каждого запроса.
_QUIET_LIBRARIES = ("httpx", "httpcore")


def add_request_id(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    request_id = get_correlation_id()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_request_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]


def configure_logging(settings: Settings) -> None:
    renderer: Processor
    if settings.log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)

    structlog.configure(
        processors=[*_shared_processors(), structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != _HANDLER_NAME]
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    for name in _QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(max(logging.WARNING, logging.getLogger(name).level))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # Журнал запросов ведёт AccessLogMiddleware (с длительностью, без /health); access-лог uvicorn дублировал бы его.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class AccessLogMiddleware:
    """ASGI: одна запись на запрос (метод, путь без query, статус, длительность). `/health` не пишется."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = structlog.get_logger("eds.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status: dict[str, Any] = {"code": 500}

        async def send_logged(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_logged)
        finally:
            if scope["path"] != "/health":
                self.log.info(
                    "request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status["code"],
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
