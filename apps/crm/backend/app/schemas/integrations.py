"""DTO «Подключений»: статус бота без значения токена, смена токена с паролем, каналы, ERP."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.schemas.settings_profile import BotProfileSettings


class TelegramStatusOut(BaseModel):
    """Значение токена сюда не попадает никогда — только `configured` и `last4`."""

    configured: bool
    source: Literal["db", "env", "none"]
    last4: str | None
    updated_at: datetime | None
    username: str | None
    mode: str
    running: bool
    last_error: str | None
    secrets_enabled: bool
    channel_id: int | None
    channel_title: str | None


class TelegramTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(min_length=20, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=256)


class ChatCandidateOut(BaseModel):
    chat_id: int
    title: str
    chat_type: str
    detected_at: datetime


class ProfilePublishOut(BaseModel):
    """Итог последней публикации профиля в Telegram; `error` — код, текст — на фронте."""

    ok: bool
    at: datetime
    changed: int
    error: Literal["rate_limited", "telegram_error", "bot_not_running"] | None
    retry_after: int | None


class BotProfileOut(BaseModel):
    profile: BotProfileSettings
    # None — с запуска API профиль ещё не публиковался (бот не запущен).
    published: ProfilePublishOut | None


class ErpStatusOut(BaseModel):
    """Коннектор «ERP» (M3-CRM-02): значения секретов не возвращаются — только «задан» и `last4`."""

    configured: bool
    mode: Literal["local", "erp"]
    base_url: str
    base_url_source: Literal["db", "env", "none"]
    token_configured: bool
    token_source: Literal["db", "env", "none"]
    token_last4: str | None
    token_updated_at: datetime | None
    webhook_secret_configured: bool
    webhook_secret_source: Literal["db", "env", "none"]
    webhook_secret_last4: str | None
    webhook_secret_updated_at: datetime | None
    # Ротация без простоя (FIX-35): предыдущий секрет принимается, пока его не сняли.
    webhook_secret_previous_configured: bool
    webhook_secret_previous_source: Literal["db", "env", "none"]
    webhook_secret_previous_last4: str | None
    webhook_secret_previous_updated_at: datetime | None
    secrets_enabled: bool
    # Сопряжение «Подключить ERP» (M3-CRM-10): токен ERP→CRM выдала CRM; `paired` — ключи выданы
    # сопряжением.
    inbound_token_configured: bool = False
    inbound_token_last4: str | None = None
    paired: bool = False
    # Переход после «Обновить ключи»: до какого момента принимается предыдущий секрет вебхуков.
    previous_secret_until: datetime | None = None
    # «Обновить ключи» не доведено до ответа ERP (обрыв связи): повтор отправит ту же тройку.
    rotation_pending: bool = False


class ErpConnectorIn(BaseModel):
    """Сохранение коннектора: секрет `None` — оставить прежний; пустой адрес выключает коннектор."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(max_length=500)
    service_token: SecretStr | None = Field(default=None, min_length=16, max_length=512)
    webhook_secret: SecretStr | None = Field(default=None, min_length=16, max_length=512)
    # Ротация секрета вебхуков: предыдущий секрет CRM принимает наравне с текущим, пока его не
    # сняли.
    webhook_secret_previous: SecretStr | None = Field(default=None, min_length=16, max_length=512)
    clear_webhook_secret_previous: bool = False
    password: SecretStr = Field(min_length=1, max_length=256)

    @field_validator("service_token", "webhook_secret", "webhook_secret_previous")
    @classmethod
    def _secret_not_blank(cls, value: SecretStr | None) -> SecretStr | None:
        """Сервис сохраняет секрет после `strip()`: из одних пробелов получился бы пустой секрет."""
        if value is not None and len(value.get_secret_value().strip()) < 16:
            raise ValueError("secret must have at least 16 characters besides whitespace")
        return value


class ErpPairIn(BaseModel):
    """«Подключить ERP»: адрес ERP и одноразовый код из её настроек; пароль админа — как всегда."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1, max_length=500)
    code: SecretStr = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=256)


class ErpRotateIn(BaseModel):
    """«Обновить ключи»: только пароль админа — новые секреты CRM генерирует сама."""

    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=1, max_length=256)


class ErpCheckOut(BaseModel):
    """Ответ ERP на `GET /api/integration/v1/health` (схема `Health` контракта) и время ответа."""

    status: Literal["ok", "degraded"]
    version: str
    migrations_applied: bool
    queue_alive: bool
    checked_at: datetime
    latency_ms: int


class ErpPairingOut(BaseModel):
    """Итог сопряжения или ротации: состояние коннектора и «Проверить связь», сделанная сразу после.

    Сопряжение удалось, даже если проверка не прошла: тогда `check` пуст, а `check_error` — подкод
    причины (`erp_unauthorized`, `erp_unavailable`, …) для понятной подсказки.
    """

    status: ErpStatusOut
    check: ErpCheckOut | None
    check_error: str | None


Source = Literal["db", "env", "none"]
EmailStatus = Literal["queued", "sent", "failed", "skipped_no_smtp"]


class SmtpStatusOut(BaseModel):
    """Коннектор «Почта» (M3-CRM-08): пароль не возвращается — только «задан» и `last4`."""

    configured: bool
    host: str
    port: int
    security: Literal["starttls", "ssl", "none"]
    from_email: str
    from_name: str
    settings_source: Source
    username: str
    username_source: Source
    password_configured: bool
    password_source: Source
    password_last4: str | None
    password_updated_at: datetime | None
    secrets_enabled: bool


class SmtpConnectorIn(BaseModel):
    """Сохранение коннектора: логин/пароль `None` — оставить прежние; пустой хост выключает."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(max_length=253)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] = "starttls"
    from_email: str = Field(default="", max_length=255)
    from_name: str = Field(default="", max_length=120)
    username: str | None = Field(default=None, max_length=255)
    smtp_password: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    password: SecretStr = Field(min_length=1, max_length=256)


class SmtpCheckOut(BaseModel):
    """Итог «Проверить связь»: приветствие сервера, выполнен ли вход, время ответа."""

    server: str
    authenticated: bool
    latency_ms: int


class EmailLogItem(BaseModel):
    """Строка журнала писем; тела письма (временного пароля) в журнале нет."""

    id: int
    to_email: str
    subject: str
    template: str
    lang: str
    status: EmailStatus
    error: str | None
    attempts: int
    user_id: int | None
    requested_by: int | None
    created_at: datetime
    sent_at: datetime | None


class EmailQueuedOut(BaseModel):
    """Письмо поставлено в очередь: номер строки журнала, адрес получателя, статус."""

    email_log_id: int
    to_email: str
    status: EmailStatus
