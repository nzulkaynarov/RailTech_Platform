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
    KB_MARKDOWN_ONLY = "kb_markdown_only"
    KB_FORMAT = "kb_format"
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
    # Зеркальная сделка ERP: сумму, валюту, стадию, название и причину отказа ведёт бэк-офис (I-26).
    DEAL_OWNED_BY_ERP = "deal_owned_by_erp"
    NO_CONSENT = "no_consent"
    # Ответ с этим ключом повтора ещё отправляется (D1-1): повтор не шлёт сообщение второй раз.
    REPLY_IN_PROGRESS = "reply_in_progress"
    # Итог отправки ответа неизвестен: Telegram не ответил вовремя (502) или так и не
    # подтвердил доставку (409).
    DELIVERY_UNKNOWN = "delivery_unknown"
    DELIVERY_UNCONFIRMED = "delivery_unconfirmed"
    LITELLM_UNAVAILABLE = "litellm_unavailable"
    MODEL_KEY_REQUIRED = "model_key_required"
    MODEL_IN_CONFIG = "model_in_config"
    # Коннектор «ERP» (M3-CRM-02, ADR-0018): адрес, токен и «Проверить связь».
    ERP_NOT_CONFIGURED = "erp_not_configured"
    ERP_INVALID_URL = "erp_invalid_url"
    ERP_UNAUTHORIZED = "erp_unauthorized"
    ERP_UNAVAILABLE = "erp_unavailable"
    ERP_BAD_RESPONSE = "erp_bad_response"
    # Лимит сервисного токена ERP (429 `TOO_MANY_REQUESTS` + `Retry-After`, шов 0.3.0, FIX-60).
    ERP_RATE_LIMITED = "erp_rate_limited"
    # Повторное приглашение в кабинет (D1-9): клиент ещё не передан в ERP — приглашать некуда.
    CLIENT_NOT_IN_ERP = "client_not_in_erp"
    # Передача клиента (FIX-31): ИНН уже принадлежит другому клиенту CRM в ERP (409 INN_CONFLICT).
    ERP_INN_CONFLICT = "erp_inn_conflict"
    # Сопряжение с ERP по одноразовому коду (M3-CRM-10): код не принят, просрочен или уже
    # использован; ERP старой версии без операции сопряжения.
    ERP_PAIRING_CODE_INVALID = "erp_pairing_code_invalid"
    ERP_PAIRING_CODE_EXPIRED = "erp_pairing_code_expired"
    ERP_PAIRING_CODE_USED = "erp_pairing_code_used"
    ERP_PAIRING_UNSUPPORTED = "erp_pairing_unsupported"
    # В проде адрес ERP — только https: ключи и код сопряжения не идут по открытому каналу.
    ERP_HTTPS_REQUIRED = "erp_https_required"
    # Сопряжение без кода (bootstrap, ADR-0009): ERP не приняла доказательство, окно закрыто
    # навсегда или у CRM нет общего секрета платформы.
    ERP_BOOTSTRAP_REJECTED = "erp_bootstrap_rejected"
    ERP_BOOTSTRAP_CLOSED = "erp_bootstrap_closed"
    ERP_BOOTSTRAP_UNAVAILABLE = "erp_bootstrap_unavailable"
    # Коннектор «Почта» (M3-CRM-08, ADR-0018): SMTP-релей для писем сотрудникам.
    SMTP_NOT_CONFIGURED = "smtp_not_configured"
    SMTP_INVALID_HOST = "smtp_invalid_host"
    SMTP_UNAVAILABLE = "smtp_unavailable"
    SMTP_AUTH_FAILED = "smtp_auth_failed"
    SMTP_TLS_FAILED = "smtp_tls_failed"
    SMTP_REJECTED = "smtp_rejected"
    # Внешняя копия бэкапов на Google Drive (OPS-GDRIVE-2): ключ или ID папки не те, нет
    # настройки, ключ не дошёл до сервиса копирования (хранилище RustFS недоступно).
    OFFSITE_KEY_INVALID = "offsite_key_invalid"
    OFFSITE_FOLDER_INVALID = "offsite_folder_invalid"
    OFFSITE_NOT_CONFIGURED = "offsite_not_configured"
    OFFSITE_DELIVERY_FAILED = "offsite_delivery_failed"
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
    # Токен сотрудника для EDS (волна 12, E4): нет прав EDS (`permissions.eds` пуст) или нет вовсе.
    EDS_ACCESS_DENIED = "eds_access_denied"
    USER_NOT_PROVISIONED = "user_not_provisioned"
    USER_INACTIVE = "user_inactive"
    # Синхронизация сотрудников с ERP: e-mail занят другим пользователем ERP (409 EMAIL_CONFLICT).
    ERP_EMAIL_CONFLICT = "erp_email_conflict"
    # Правила ADR-0022 на бэкенде (FIX-34): «Сделка заключена» в режиме `erp` решает бэк-офис;
    # передать в ERP лида, не давшего согласие, нельзя.
    WON_DECIDED_BY_ERP = "won_decided_by_erp"
    HANDOFF_NO_CONSENT = "handoff_no_consent"
    # «Согласие получено» (FIX-57, D-8): лид из Telegram соглашается в боте, сотрудник не отмечает.
    CONSENT_VIA_BOT = "consent_via_bot"
    # Профиль сотрудника (W15-H6): значения полей, фото и замещение (`domain/staff_profile.py`).
    NAME_REQUIRED = "name_required"
    PHONE_INVALID = "phone_invalid"
    TIMEZONE_UNKNOWN = "timezone_unknown"
    SIGNATURE_INVALID = "signature_invalid"
    AVATAR_EMPTY = "avatar_empty"
    AVATAR_TOO_LARGE = "avatar_too_large"
    AVATAR_UNSUPPORTED_TYPE = "avatar_unsupported_type"
    AVATAR_TYPE_MISMATCH = "avatar_type_mismatch"
    DEPUTY_IS_SELF = "deputy_is_self"
    DEPUTY_PERIOD_REVERSED = "deputy_period_reversed"
    DEPUTY_PERIOD_PAST = "deputy_period_past"
    DEPUTY_PERIOD_TOO_LONG = "deputy_period_too_long"
    DEPUTY_NOT_COLLEAGUE = "deputy_not_colleague"
    NOT_A_DEPUTY = "not_a_deputy"
    # Сброс пароля по ссылке: токен неверный, использован или просрочен (один код на все случаи).
    RESET_TOKEN_INVALID = "reset_token_invalid"  # noqa: S105 — подкод ошибки, не секрет
    # Обращения сотрудников к администратору (W15-H7)
    TICKET_SUBJECT_UNKNOWN = "ticket_subject_unknown"
    TICKET_TEXT_EMPTY = "ticket_text_empty"
    TICKET_TEXT_TOO_LONG = "ticket_text_too_long"
    TICKET_PAGE_INVALID = "ticket_page_invalid"
    TICKET_STATUS_UNKNOWN = "ticket_status_unknown"
    TICKET_STATUS_TRANSITION = "ticket_status_transition"
    TICKET_REPLY_EMPTY = "ticket_reply_empty"
    TICKET_REPLY_TOO_LONG = "ticket_reply_too_long"
    TICKET_RATE_LIMITED = "ticket_rate_limited"
    # Статьи компании (W18A-P5, B-079)
    ARTICLE_TITLE_EMPTY = "article_title_empty"
    ARTICLE_TITLE_TOO_LONG = "article_title_too_long"
    ARTICLE_BODY_EMPTY = "article_body_empty"
    ARTICLE_BODY_TOO_LONG = "article_body_too_long"
    ARTICLE_LANGUAGE_UNKNOWN = "article_language_unknown"
    ARTICLE_STATUS_UNKNOWN = "article_status_unknown"
    # «Создать заявку» (W16-D1-2, CRM-03): у контакта нет ни одного канала связи; лид в отказе или
    # обезличен.
    CONTACT_CHANNEL_REQUIRED = "contact_channel_required"
    REQUEST_NOT_ALLOWED = "request_not_allowed"
    # Ключ формы `request_key` уже занят заявкой другого лида или клиента.
    REQUEST_KEY_REUSED = "request_key_reused"
    # ERP: тот же ключ идемпотентности заявки с другим телом (409 `IDEMPOTENCY_CONFLICT`) — заявка
    # не создана, автоповтора нет.
    ERP_REQUEST_CONFLICT = "erp_request_conflict"
    # «Повторить отправку в ERP» (B-082): заявка не в ошибке или ошибка постоянная (тело заявки
    # изменилось после первой отправки — ERP ответила `IDEMPOTENCY_CONFLICT`).
    REQUEST_NOT_FAILED = "request_not_failed"
    REQUEST_NOT_RETRYABLE = "request_not_retryable"


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


class LastDirectorError(ConflictError):
    """Компания не остаётся без активного директора (ADR-0012 п. 2)."""

    code = "last_director"


class RoleSystemError(ConflictError):
    """Системную роль («Администратор», «Директор») нельзя изменить или удалить (ADR-0012 п. 2)."""

    code = "role_system"


class RoleInUseError(ConflictError):
    """Роль выдана сотрудникам: сначала переназначьте их; `details.users` — сколько (ADR-0012)."""

    code = "role_in_use"


class RoleVersionConflictError(ConflictError):
    """Роль изменена другим администратором после того, как её прочитал клиент (R-1b)."""

    code = "role_version_conflict"


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


class RolesRequiredError(ValidationFailedError):
    """Пустой набор ролей Платформы (R3-D-1): у сотрудника хотя бы одна роль, закрыть доступ —
    отключить сотрудника (422, `details.field = platform_role_ids`)."""

    code = "roles_required"


class UpstreamUnavailableError(DomainError):
    """Внешний сервис (Telegram) не ответил или отказал (502)."""

    code = "upstream_unavailable"


class ErpRateLimitedError(UpstreamUnavailableError):
    """ERP ограничила частоту запросов сервисного токена: повторить через `retry_after_s` секунд.

    Временный сбой: очередь повторяет не по своему расписанию, а после этой паузы
    (`tasks/erp_retry.py`); «Проверить связь» показывает статус, а не ошибку.
    """

    def __init__(self, retry_after_s: int, message: str = "") -> None:
        super().__init__(
            message or f"erp rate limited, retry in {retry_after_s}s",
            reason=Reason.ERP_RATE_LIMITED,
            retry_after_s=retry_after_s,
        )
        self.retry_after_s = retry_after_s


class MailTemplateMissingError(DomainError):
    """В образе или стенде нет файла шаблона письма (ошибка развёртывания, не запроса): 500 с кодом.

    Сообщение без путей и имён файлов; шаблон и язык — в логе сервера (`mail_template_missing`).
    """

    code = "mail_template_missing"

    def __init__(self) -> None:
        super().__init__("email template is not found; contact the administrator of the deployment")


class PayloadTooLargeError(DomainError):
    """Тело запроса больше допустимого (413): тело не читается дальше предела."""

    code = "payload_too_large"


class RateLimitedError(DomainError):
    """Слишком много запросов с одного адреса (429) — публичная форма «Запрос»."""

    code = "rate_limited"
