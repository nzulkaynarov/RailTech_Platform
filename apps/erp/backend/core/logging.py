"""Structured logging helpers: request-id propagation + a dependency-free JSON
log formatter.

Both are opt-in and default-safe:
  * The JSON formatter is only selected when DJANGO_LOG_FORMAT=json (otherwise
    the human-readable console formatter is used, unchanged).
  * RequestIDMiddleware always runs but is cheap; it stamps every request with
    an id (from the inbound X-Request-ID header or a fresh uuid4) so logs and
    the response header can be correlated. Celery tasks read the same contextvar
    when a caller sets it.

Why no external dep: the platform audit (2026-06-18) flagged the lack of
structured logging as a production-debuggability gap. python-json-logger /
structlog would also work, but a ~30-line formatter avoids touching the
dependency lockfile.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
import time
import uuid
from contextvars import ContextVar

# Holds the current request/task correlation id. Defaults to "-" so logs emitted
# outside any request (startup, management commands) still format cleanly.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDFilter(logging.Filter):
    """Inject the current request id onto every LogRecord as `request_id`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


# Секретный токен в пути запроса; `django.request` и access-логи пишут путь целиком (FIX-14, P-9; FIX-55, D-14):
# вход в портал (`/auth/magic/<токен>`) и публичные ссылки на КП, документы и подписанные ссылки CRM на файл
# (`/public/quotes|documents|doc-links/<токен>/…`).
_SECRET_PATH_TOKEN_RE = re.compile(r"(/auth/magic/|/public/(?:quotes|documents|doc-links)/)[^/?#&\s\"'<>]+")
_SECRET_PATH_MARKERS = ("/auth/magic/", "/public/quotes/", "/public/documents/", "/public/doc-links/")


class RedactPortalTokenFilter(logging.Filter):
    """Заменяет токен magic-link и токены публичных ссылок на документы в пути запроса на [REDACTED] в любой записи."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if any(marker in message for marker in _SECRET_PATH_MARKERS):
            record.msg = _SECRET_PATH_TOKEN_RE.sub(r"\1[REDACTED]", message)
            record.args = ()
        return True


# Standard LogRecord attributes — everything else on a record is treated as a
# structured extra and merged into the JSON payload.
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"request_id", "asctime", "message"}


class JSONFormatter(logging.Formatter):
    """Minimal JSON line formatter. One JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": _dt.datetime.fromtimestamp(record.created, tz=_dt.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "module": record.module,
            "process": record.process,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Merge any structured extras passed via logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


class RequestIDMiddleware:
    """Stamp each HTTP request with a correlation id and echo it back.

    Reads an inbound `X-Request-ID` (set by an upstream proxy/load balancer) or
    generates a uuid4. The id is exposed on `request.request_id`, stored in the
    contextvar for the duration of the request, and returned as the
    `X-Request-ID` response header.
    """

    HEADER = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get("HTTP_X_REQUEST_ID", "").strip()
        request_id = incoming or uuid.uuid4().hex
        request.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response[self.HEADER] = request_id
        return response


access_logger = logging.getLogger("core.access")


class AccessLogMiddleware:
    """Журнал запросов средствами Django вместо access-лога Daphne (FIX-15, хвост ревью FIX-14).

    Daphne печатает путь запроса в stdout мимо фильтров журнала, а путь ссылки входа в портал несёт токен
    (`/auth/magic/<токен>`). Поэтому access-лог Daphne выключен (`daphne -v 0`, infra/compose/base.yml), а строка
    «метод путь статус время» пишется здесь — через обработчик `console` с `RedactPortalTokenFilter`. Только путь,
    без строки запроса: в ней тоже бывают токены.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        try:
            response = self.get_response(request)
        except Exception:
            # Django превращает исключения вида/внутренних middleware в ответы (404, 410, 500) до этого слоя;
            # сюда исключение попадает, только если что-то пробросило его наружу. Строка пишется и в этом случае.
            self._log(request, 500, started)
            raise
        self._log(request, response.status_code, started)
        return response

    @staticmethod
    def _log(request, status_code, started):
        access_logger.info(
            "%s %s %s %dms", request.method, request.path, status_code, (time.monotonic() - started) * 1000
        )
