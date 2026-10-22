"""Единый формат ошибок BFF — схема `Error` из packages/contracts/openapi/platform-bff.yaml."""

from typing import Any, Literal, cast

import httpx
import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.exceptions import RedisError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.cookies import clear_session_cookies

log = structlog.get_logger()

Source = Literal["bff", "crm", "erp"]

_CODES: dict[int, tuple[str, str]] = {
    status.HTTP_401_UNAUTHORIZED: ("SESSION_EXPIRED", "Сессия истекла. Войдите снова."),
    status.HTTP_403_FORBIDDEN: ("FORBIDDEN", "Раздел или действие не положены вашей роли."),
    status.HTTP_404_NOT_FOUND: ("NOT_FOUND", "Не найдено."),
    status.HTTP_409_CONFLICT: ("CONFLICT", "Объект изменился. Обновите страницу."),
    status.HTTP_429_TOO_MANY_REQUESTS: (
        "TOO_MANY_REQUESTS",
        "Слишком много запросов. Повторите позже.",
    ),
    status.HTTP_503_SERVICE_UNAVAILABLE: ("BACKEND_UNAVAILABLE", "Сервис временно недоступен."),
}


_NAMED_4XX: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
}


def _fallback(status_code: int) -> tuple[str, str]:
    """Статус вне таблицы: 4xx — нейтральный код по статусу, INTERNAL_ERROR — только 5xx."""
    if 400 <= status_code < 500:
        code = _NAMED_4XX.get(status_code, f"HTTP_{status_code}")
        return code, "Запрос не может быть выполнен."
    return "INTERNAL_ERROR", "Ошибка сервера."


class ErrorBody(BaseModel):
    code: str
    message: str
    source: Source
    details: dict[str, Any] | None = None


class PlatformError(Exception):
    """Ошибка с кодом контракта; бросается из маршрутов и клиентов CRM и ERP."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        source: Source = "bff",
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        clear_session: bool = False,
    ) -> None:
        super().__init__(message)
        self.body = ErrorBody(code=code, message=message, source=source, details=details)
        self.status_code = status_code
        self.headers = headers
        # Сессии больше нет: вместе с ошибкой браузеру уходит сброс cookie `rt_pf_*`.
        self.clear_session = clear_session


def error_response(
    status_code: int, body: ErrorBody, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=headers,
    )


async def _platform_error(request: Request, exc: Exception) -> JSONResponse:
    err = cast(PlatformError, exc)
    response = error_response(err.status_code, err.body, err.headers)
    if err.clear_session:
        settings = getattr(request.app.state, "settings", None)
        clear_session_cookies(response, secure=settings.cookie_secure if settings else True)
    return response


async def _redis_error(_: Request, exc: Exception) -> JSONResponse:
    log.error("redis_error", error=type(exc).__name__)
    code, message = _CODES[status.HTTP_503_SERVICE_UNAVAILABLE]
    return error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE, ErrorBody(code=code, message=message, source="bff")
    )


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    err = cast(StarletteHTTPException, exc)
    code, message = _CODES.get(err.status_code) or _fallback(err.status_code)
    body = ErrorBody(code=code, message=message, source="bff")
    return error_response(err.status_code, body, dict(err.headers) if err.headers else None)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    err = cast(RequestValidationError, exc)
    fields = [".".join(str(p) for p in e["loc"]) for e in err.errors()]
    body = ErrorBody(
        code="VALIDATION_FAILED",
        message="Проверьте заполнение полей.",
        source="bff",
        details={"fields": fields},
    )
    return error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, body)


async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_error", exc_info=exc)
    body = ErrorBody(code="INTERNAL_ERROR", message="Ошибка сервера.", source="bff")
    return error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, body)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(PlatformError, _platform_error)
    app.add_exception_handler(RedisError, _redis_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)


def session_expired() -> PlatformError:
    """Сессии нет, истекла или отозвана: 401 и сброс cookie."""
    code, message = _CODES[status.HTTP_401_UNAUTHORIZED]
    return PlatformError(code, message, status_code=401, clear_session=True)


def backend_unavailable(source: Source, reason: str | None = None) -> PlatformError:
    code, message = _CODES[status.HTTP_503_SERVICE_UNAVAILABLE]
    details = {"reason": reason} if reason else None
    return PlatformError(code, message, status_code=503, source=source, details=details)


_MESSAGES: dict[str, str] = {
    **dict(_CODES.values()),
    "VALIDATION_FAILED": "Проверьте заполнение полей.",
}
_BACKEND_CODES: dict[int, str] = {
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "VALIDATION_FAILED",
    status.HTTP_423_LOCKED: "TOO_MANY_REQUESTS",
    status.HTTP_429_TOO_MANY_REQUESTS: "TOO_MANY_REQUESTS",
}


def backend_code(response: httpx.Response) -> str | None:
    """Код ошибки бэкенда: у CRM `code` в теле, у ERP `detail`."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    value = body.get("code") or body.get("detail")
    return value if isinstance(value, str) else None


def backend_reason(response: httpx.Response) -> str | None:
    """Подкод `details.reason` ошибки CRM (например `wrong_password`)."""
    try:
        body = response.json()
    except ValueError:
        return None
    details = body.get("details") if isinstance(body, dict) else None
    reason = details.get("reason") if isinstance(details, dict) else None
    return reason if isinstance(reason, str) else None


def from_backend(source: Source, response: httpx.Response) -> PlatformError:
    """Ответ бэкенда 4xx -> ошибка BFF в формате `Error`; код и статус бэкенда — в `details`."""
    code = _BACKEND_CODES.get(response.status_code)
    if code is None:
        return backend_unavailable(source, f"HTTP {response.status_code}")
    message = _MESSAGES[code]
    details: dict[str, Any] = {"backend_status": response.status_code}
    if (b_code := backend_code(response)) is not None:
        details["backend_code"] = b_code
    headers = None
    if code == "TOO_MANY_REQUESTS":
        headers = {"Retry-After": response.headers.get("Retry-After", "60")}
    return PlatformError(
        code,
        message,
        status_code=429 if code == "TOO_MANY_REQUESTS" else response.status_code,
        source=source,
        details=details,
        headers=headers,
    )
