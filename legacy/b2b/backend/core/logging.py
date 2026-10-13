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
