"""Единый перевод исключений домена в HTTP (CLAUDE.md §4)."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

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


def status_for(exc: e.DomainError) -> int:
    for cls in type(exc).__mro__:
        if cls in STATUS:
            return STATUS[cls]
    if exc.code == "delivery_failed":
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_400_BAD_REQUEST


async def domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, e.DomainError)  # noqa: S101 — зарегистрирован только для DomainError
    body = {"code": exc.code, "message": exc.message, "details": exc.details}
    return JSONResponse(body, status_code=status_for(exc))


def install(app: FastAPI) -> None:
    app.add_exception_handler(e.DomainError, domain_error_handler)
