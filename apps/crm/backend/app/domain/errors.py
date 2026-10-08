"""Исключения домена. API переводит их в HTTP одним обработчиком (`api/errors.py`)."""


class DomainError(Exception):
    """Базовое исключение; `code` — машинно-читаемый код для фронта."""

    code = "domain_error"

    def __init__(self, message: str = "", **details: object) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details


class NotFoundError(DomainError):
    code = "not_found"


class ConflictError(DomainError):
    """Действие противоречит текущему состоянию (409)."""

    code = "conflict"


class LastAdminError(ConflictError):
    code = "last_admin"


class InvalidTransitionError(ConflictError):
    code = "invalid_transition"


class ForbiddenError(DomainError):
    """Объектная проверка прав (не владелец лида и т. п.)."""

    code = "forbidden"


class AuthError(DomainError):
    code = "auth_failed"


class AccountLockedError(AuthError):
    code = "account_locked"


class PasswordChangeRequiredError(DomainError):
    code = "password_change_required"


class ValidationFailedError(DomainError):
    code = "validation_failed"
