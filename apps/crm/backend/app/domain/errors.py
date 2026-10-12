"""Исключения домена. API переводит их в HTTP одним обработчиком (`api/errors.py`).

Тело ошибки: `{"code", "message", "details"}`. `code` — класс ошибки (`conflict`,
`validation_failed`, …); `details.reason` — стабильный подкод конкретного случая
(`Reason`), `details.field` — поле формы. `message` — для логов, не для показа.
"""

from enum import StrEnum


class Reason(StrEnum):
    """Подкоды `details.reason` — контракт с фронтом: значения не переименовывать."""

    EMAIL_TAKEN = "email_taken"
    INVALID_EMAIL = "invalid_email"
    TELEGRAM_TAKEN = "telegram_taken"
    TELEGRAM_LINKED_ELSEWHERE = "telegram_linked_elsewhere"
    TELEGRAM_UNKNOWN = "telegram_unknown"
    TELEGRAM_NOT_LINKED = "telegram_not_linked"
    TELEGRAM_REFUSED = "telegram_refused"
    BOT_NOT_CONFIGURED = "bot_not_configured"
    WRONG_PASSWORD = "wrong_password"  # noqa: S105 — подкод ошибки, не секрет
    SAME_PASSWORD = "same_password"  # noqa: S105 — подкод ошибки, не секрет
    WEAK_PASSWORD = "weak_password"  # noqa: S105 — подкод ошибки, не секрет
    INACTIVE_COLLEAGUE = "inactive_colleague"
    LEAD_TAKEN = "lead_taken"
    TAKE_FIRST = "take_first"
    DEAL_NOT_CLOSED = "deal_not_closed"
    NOT_LEAD_OWNER = "not_lead_owner"
    ALREADY_WITH_BOT = "already_with_bot"
    NO_OPEN_HANDOFF = "no_open_handoff"
    SNOOZE_RANGE = "snooze_range"
    SERVICE_REQUEST_CLOSED = "service_request_closed"
    FILE_TOO_LARGE = "file_too_large"
    FILE_EMPTY = "file_empty"
    FILE_TYPE = "file_type"
    DOCUMENT_INDEXING = "document_indexing"


class DomainError(Exception):
    """Базовое исключение; `code` — машинно-читаемый код для фронта, `reason` — подкод."""

    code = "domain_error"

    def __init__(
        self, message: str = "", *, reason: Reason | None = None, **details: object
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details: dict[str, object] = (
            {"reason": reason.value, **details} if reason is not None else details
        )


class NotFoundError(DomainError):
    code = "not_found"


class ConflictError(DomainError):
    """Действие противоречит текущему состоянию (409)."""

    code = "conflict"


class LastAdminError(ConflictError):
    code = "last_admin"


class ActiveLeadsError(ConflictError):
    """Деактивация менеджера, который ведёт лидов, без передачи их коллеге (ADR-0015)."""

    code = "user_has_active_leads"


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
