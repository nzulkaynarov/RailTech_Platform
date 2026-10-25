"""Единый формат ошибок — схема `Error` из packages/contracts/openapi/eds.yaml (как у BFF).

Любая ошибка API — тело `{"code", "message", "source": "eds", "details"}`: ошибки домена (`EdsError`),
ошибки валидации запроса (`VALIDATION_FAILED`, `details.fields`), `HTTPException` и необработанные исключения
(`INTERNAL_ERROR`, без подробностей наружу). Тексты — для сотрудника, по-русски; перевод — вместе с экранами (этап D).
"""

from typing import Any, Literal

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)

# Статус → (код, текст) для HTTPException без собственного кода.
_HTTP_CODES: dict[int, tuple[str, str]] = {
    status.HTTP_401_UNAUTHORIZED: ("UNAUTHORIZED", "Требуется вход."),
    status.HTTP_403_FORBIDDEN: ("FORBIDDEN", "Действие не положено вашей роли."),
    status.HTTP_404_NOT_FOUND: ("NOT_FOUND", "Не найдено."),
    status.HTTP_405_METHOD_NOT_ALLOWED: ("BAD_REQUEST", "Метод не поддерживается."),
    status.HTTP_409_CONFLICT: ("CONFLICT", "Объект изменился. Обновите страницу."),
    status.HTTP_413_CONTENT_TOO_LARGE: ("PAYLOAD_TOO_LARGE", "Слишком большой запрос."),
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: (
        "UNSUPPORTED_MEDIA_TYPE",
        "Тип содержимого не поддерживается.",
    ),
}


class ErrorBody(BaseModel):
    code: str
    message: str
    source: Literal["eds"] = "eds"
    details: dict[str, Any] | None = None


class EdsError(Exception):
    """Ошибка с кодом контракта; бросается из зависимостей, сервисов и маршрутов."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.body = ErrorBody(code=code, message=message, details=details)
        self.status_code = status_code
        self.headers = headers


def unauthorized(reason: str) -> EdsError:
    """401 `UNAUTHORIZED`: нет, неверный или истёкший токен доступа (`details.reason`)."""
    return EdsError(
        "UNAUTHORIZED",
        "Требуется вход.",
        status_code=status.HTTP_401_UNAUTHORIZED,
        details={"reason": reason},
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(permissions: tuple[str, ...]) -> EdsError:
    details: dict[str, Any] = {"permission": permissions[0]}
    if len(permissions) > 1:
        details["permissions"] = list(permissions)
    return EdsError(
        "FORBIDDEN",
        "Действие не положено вашей роли.",
        status_code=status.HTTP_403_FORBIDDEN,
        details=details,
    )


def _response(status_code: int, body: ErrorBody, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(body.model_dump(exclude_none=True), status_code=status_code, headers=headers)


async def eds_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, EdsError)  # noqa: S101 — зарегистрирован только для EdsError
    return _response(exc.status_code, exc.body, exc.headers)


async def validation_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    fields = [
        {
            "field": ".".join(str(p) for p in err.get("loc", ()) if p != "body") or None,
            "message": err.get("msg"),
            "type": err.get("type"),
        }
        for err in exc.errors()
    ]
    body = ErrorBody(code="VALIDATION_FAILED", message="Проверьте заполнение полей.", details={"fields": fields})
    return _response(status.HTTP_422_UNPROCESSABLE_CONTENT, body)


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code, message = _HTTP_CODES.get(exc.status_code, _fallback(exc.status_code))
    return _response(exc.status_code, ErrorBody(code=code, message=message), getattr(exc, "headers", None))


async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", exc_info=exc)
    body = ErrorBody(code="INTERNAL_ERROR", message="Ошибка сервера.")
    return _response(status.HTTP_500_INTERNAL_SERVER_ERROR, body)


def _fallback(status_code: int) -> tuple[str, str]:
    if 400 <= status_code < 500:
        return "BAD_REQUEST", "Запрос не может быть выполнен."
    return "INTERNAL_ERROR", "Ошибка сервера."


def install(app: FastAPI) -> None:
    app.add_exception_handler(EdsError, eds_error_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_handler)


def not_found(message: str = "Не найдено.") -> EdsError:
    """404 `NOT_FOUND`: объекта нет или он не виден сотруднику (существование не раскрывается)."""
    return EdsError("NOT_FOUND", message, status_code=status.HTTP_404_NOT_FOUND)


def conflict(reason: str, message: str, **details: Any) -> EdsError:
    """409 `CONFLICT` с `details.reason`: `invalid_state`, `route_closed`, `checklist_not_green` и др."""
    return EdsError("CONFLICT", message, status_code=status.HTTP_409_CONFLICT, details={"reason": reason, **details})


def forbidden_reason(reason: str, message: str) -> EdsError:
    """403 `FORBIDDEN` с `details.reason` — действие не положено сотруднику при наличии права на операцию."""
    return EdsError("FORBIDDEN", message, status_code=status.HTTP_403_FORBIDDEN, details={"reason": reason})


def invalid_fields(message: str, **fields: str) -> EdsError:
    """422 `VALIDATION_FAILED`: `details.fields` — `[{field, message, type}]`, как у ошибок разбора запроса."""
    items = [{"field": name, "message": text, "type": "value_error"} for name, text in fields.items()]
    return EdsError(
        "VALIDATION_FAILED",
        message,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        details={"fields": items},
    )
