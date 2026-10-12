"""Единый перевод ошибок в HTTP (CLAUDE.md §4).

Любая ошибка API — тело `{"code", "message", "details"}` (`app/domain/errors.py`):
ошибки домена, ошибки валидации запроса FastAPI (`validation_failed` + `details.field`)
и `HTTPException` (404 → `not_found`, прочие — `http_error`).
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain import errors as e

STATUS: dict[type[e.DomainError], int] = {
    e.NotFoundError: status.HTTP_404_NOT_FOUND,
    e.ConflictError: status.HTTP_409_CONFLICT,
    e.ForbiddenError: status.HTTP_403_FORBIDDEN,
    e.PasswordChangeRequiredError: status.HTTP_403_FORBIDDEN,
    e.AuthError: status.HTTP_401_UNAUTHORIZED,
    e.AccountLockedError: status.HTTP_423_LOCKED,
    e.ValidationFailedError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}
HTTP_CODES: dict[int, str] = {
    status.HTTP_401_UNAUTHORIZED: e.AuthError.code,
    status.HTTP_403_FORBIDDEN: e.ForbiddenError.code,
    status.HTTP_404_NOT_FOUND: e.NotFoundError.code,
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
}
# Служебные части пути в `loc` ошибки pydantic: ("body", "email") → поле «email».
_LOC_SOURCES = frozenset({"body", "query", "path", "header", "cookie"})


def status_for(exc: e.DomainError) -> int:
    for cls in type(exc).__mro__:
        if cls in STATUS:
            return STATUS[cls]
    if exc.code == "delivery_failed":
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_400_BAD_REQUEST


def body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}}


async def domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, e.DomainError)  # noqa: S101 — зарегистрирован только для DomainError
    return JSONResponse(body(exc.code, exc.message, exc.details), status_code=status_for(exc))


def field_of(loc: tuple[int | str, ...] | list[int | str]) -> str | None:
    """Имя поля формы из `loc` ошибки pydantic; `None`, если ошибка про тело целиком."""
    parts = [str(p) for p in loc if not isinstance(p, int) and p not in _LOC_SOURCES]
    return parts[0] if parts else None


async def request_validation_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [
        {"field": field_of(err.get("loc", ())), "type": err.get("type"), "msg": err.get("msg")}
        for err in exc.errors()
    ]
    first = next((err["field"] for err in errors if err["field"]), None)
    details: dict[str, Any] = {"errors": errors}
    if first is not None:
        details["field"] = first
    return JSONResponse(
        body(e.ValidationFailedError.code, "request validation failed", details),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = HTTP_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else code
    return JSONResponse(
        body(code, message), status_code=exc.status_code, headers=getattr(exc, "headers", None)
    )


def install(app: FastAPI) -> None:
    app.add_exception_handler(e.DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
