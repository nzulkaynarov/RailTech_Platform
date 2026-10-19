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
    INVALID_PHONE = "invalid_phone"
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
    SETUP_DONE = "setup_done"
    SETUP_CODE_INVALID = "setup_code_invalid"
    SETUP_CODE_EXPIRED = "setup_code_expired"
    SETUP_LOCKED = "setup_locked"
    INVALID_BOT_TOKEN = "invalid_bot_token"  # noqa: S105 — подкод ошибки, не секрет
    TELEGRAM_UNAVAILABLE = "telegram_unavailable"
    SECRETS_KEY_MISSING = "secrets_key_missing"
    BOT_NOT_RUNNING = "bot_not_running"
    CHANNEL_NOT_CONFIGURED = "channel_not_configured"
    CHANNEL_SEND_FAILED = "channel_send_failed"
    ASSIST_DISABLED = "assist_disabled"
    ASSIST_BUDGET = "assist_budget"
    ASSIST_UNAVAILABLE = "assist_unavailable"
    ASSIST_EMPTY = "assist_empty"
    ASSIST_NO_HISTORY = "assist_no_history"
    DEAL_WON_FINAL = "deal_won_final"
    NO_CONSENT = "no_consent"
    LITELLM_UNAVAILABLE = "litellm_unavailable"
    MODEL_KEY_REQUIRED = "model_key_required"
    MODEL_IN_CONFIG = "model_in_config"
    # Коннектор «ERP» (M3-CRM-02, ADR-0018): адрес, токен и «Проверить связь».
    ERP_NOT_CONFIGURED = "erp_not_configured"
    ERP_INVALID_URL = "erp_invalid_url"
    ERP_UNAUTHORIZED = "erp_unauthorized"
    ERP_UNAVAILABLE = "erp_unavailable"
    ERP_BAD_RESPONSE = "erp_bad_response"
    # Коннектор «Почта» (M3-CRM-08, ADR-0018): SMTP-релей для писем сотрудникам.
    SMTP_NOT_CONFIGURED = "smtp_not_configured"
    SMTP_INVALID_HOST = "smtp_invalid_host"
    SMTP_UNAVAILABLE = "smtp_unavailable"
    SMTP_AUTH_FAILED = "smtp_auth_failed"
    SMTP_TLS_FAILED = "smtp_tls_failed"
    SMTP_REJECTED = "smtp_rejected"
    # Источники лидов (M3-CRM-05): ручное создание и форма «Запрос» с сайта.
    LEAD_EXISTS = "lead_exists"
    CLIENT_EXISTS = "client_exists"
    CONTACT_REQUIRED = "contact_required"
    FORM_TOKEN_INVALID = "form_token_invalid"  # noqa: S105 — подкод ошибки, не секрет
    FORM_TOO_FAST = "form_too_fast"
    FORM_TOKEN_EXPIRED = "form_token_expired"  # noqa: S105 — подкод ошибки, не секрет
    RATE_LIMITED = "rate_limited"
    # Форма «Запрос»: согласие на обработку ПДн обязательно (DECISIONS Q-12, M2-CAB-03).
    CONSENT_REQUIRED = "consent_required"
    # «Расходы» по ансамблю (M3-CRM-09): период журнала LiteLLM — не длиннее 90 дней, без будущего.
    AI_SPEND_PERIOD = "ai_spend_period"
    # Центр внешних сервисов (M3-CRM-12, ADR-0024): выключатель недоступен; Telegram на паузе.
    SERVICE_NOT_SWITCHABLE = "service_not_switchable"
    TELEGRAM_PAUSED = "telegram_paused"
    SSO_NOT_CONFIGURED = "sso_not_configured"
    # SSO и доступ к ERP (FIX-11, M3-CRM-06): `platform_access` решает, кто может перейти в ERP.
    PLATFORM_ACCESS_DENIED = "platform_access_denied"
    USER_NOT_PROVISIONED = "user_not_provisioned"
    USER_INACTIVE = "user_inactive"
    # Синхронизация сотрудников с ERP: e-mail занят другим пользователем ERP (409 EMAIL_CONFLICT).
    ERP_EMAIL_CONFLICT = "erp_email_conflict"


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


class UpstreamUnavailableError(DomainError):
    """Внешний сервис (Telegram) не ответил или отказал (502)."""

    code = "upstream_unavailable"


class RateLimitedError(DomainError):
    """Слишком много запросов с одного адреса (429) — публичная форма «Запрос»."""

    code = "rate_limited"
