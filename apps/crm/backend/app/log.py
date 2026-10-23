"""Настройка structlog: JSON в stdout для приложения и сторонних библиотек.

Логи стандартного `logging` (uvicorn, alembic, procrastinate) проходят через
те же процессоры, поэтому формат единый. `request_id` добавляется из
контекста `asgi-correlation-id`; персональные данные маскируются
(SPEC §11). Логировать только kwargs, без f-строк.
"""

import logging
import re
import sys
from typing import Any

import structlog
from asgi_correlation_id import correlation_id
from rt_bus.context import TRACEPARENT_HEADER, correlation, valid_traceparent
from structlog.types import EventDict, Processor, WrappedLogger

from app.config import Settings
from app.security.log_mask import quiet_noisy_loggers
from app.security.log_mask import structlog_processor as mask_secrets
from app.security.pii import structlog_processor as mask_pii

_HANDLER_NAME = "structlog-stdout"
# Токен бота — в пути Bot API (`/bot<id>:<секрет>/getMe`); httpx на INFO пишет URL целиком.
_BOT_TOKEN_IN_URL = re.compile(r"bot\d+:[\w-]+")
_QUIET_LIBRARIES = ("httpx", "httpcore")


class MaskBotToken(logging.Filter):
    """Маскирует `/bot<id>:<секрет>` в любой записи stdlib-логов (FIX-66): токена нет в журнале."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "bot" in message and _BOT_TOKEN_IN_URL.search(message):
            record.msg, record.args = _BOT_TOKEN_IN_URL.sub("bot***", message), None
        return True


_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def is_valid_request_id(value: str) -> bool:
    """Приходящий `X-Request-ID` (Caddy пропускает клиентский как есть): безопасная короткая строка.

    Не только UUID4 (умолчание `asgi-correlation-id` подменило бы чужой идентификатор новым
    и разорвало цепочку журналов), но без пробелов, переводов строк и длины сверх 128.
    """
    return _REQUEST_ID.fullmatch(value) is not None


class BusCorrelationMiddleware:
    """ASGI: id запроса (`X-Request-ID`, его ставит `CorrelationIdMiddleware` выше) становится
    корреляцией шины: события, опубликованные в обработке запроса, несут `correlationid` = id
    запроса, а вместе с `traceparent` он идёт в доставку, обработчики и логи подписчиков.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        traceparent = valid_traceparent(headers.get(TRACEPARENT_HEADER.lower()))
        with correlation(correlation_id.get(), traceparent):
            await self.app(scope, receive, send)


def add_request_id(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    request_id = correlation_id.get()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_request_id,
        mask_secrets,  # до pii: иначе id из токена бота станет [number], а хвост останется
        mask_pii,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]


def configure_logging(settings: Settings) -> None:
    quiet_noisy_loggers()  # FIX-66b: библиотеки на INFO печатают URL запроса (токены, подписи)
    renderer: Processor
    if settings.log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            mask_secrets,  # FIX-66b: после format_exc_info — и текст трассировки
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.addFilter(MaskBotToken())
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != _HANDLER_NAME]
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Клиентские библиотеки на INFO пишут каждый запрос с URL — для Bot API это токен.
    for name in _QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(max(logging.WARNING, logging.getLogger(name).level))

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
