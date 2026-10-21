"""Настройка structlog: JSON в stdout для приложения и сторонних библиотек.

Логи стандартного `logging` (uvicorn, alembic, procrastinate) проходят через
те же процессоры, поэтому формат единый. `request_id` добавляется из
контекста `asgi-correlation-id`; персональные данные маскируются
(SPEC §11). Логировать только kwargs, без f-строк.
"""

import logging
import sys

import structlog
from asgi_correlation_id import correlation_id
from structlog.types import EventDict, Processor, WrappedLogger

from app.config import Settings
from app.security.log_mask import quiet_noisy_loggers
from app.security.log_mask import structlog_processor as mask_secrets
from app.security.pii import structlog_processor as mask_pii

_HANDLER_NAME = "structlog-stdout"


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
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != _HANDLER_NAME]
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
