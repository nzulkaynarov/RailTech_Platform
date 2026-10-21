"""Единый формат ошибок BFF — схема `Error` из packages/contracts/openapi/platform-bff.yaml."""

from typing import Any, Literal, cast

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    ) -> None:
        super().__init__(message)
        self.body = ErrorBody(code=code, message=message, source=source, details=details)
        self.status_code = status_code
        self.headers = headers


def error_response(
    status_code: int, body: ErrorBody, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=headers,
    )


async def _platform_error(_: Request, exc: Exception) -> JSONResponse:
    err = cast(PlatformError, exc)
    return error_response(err.status_code, err.body, err.headers)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    err = cast(StarletteHTTPException, exc)
    code, message = _CODES.get(err.status_code, ("INTERNAL_ERROR", "Ошибка сервера."))
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
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)
