"""DTO «Подключений»: статус бота без значения токена, смена токена с паролем, каналы, ERP."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

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
    secrets_enabled: bool


class ErpConnectorIn(BaseModel):
    """Сохранение коннектора: секрет `None` — оставить прежний; пустой адрес выключает коннектор."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(max_length=500)
    service_token: SecretStr | None = Field(default=None, min_length=16, max_length=512)
    webhook_secret: SecretStr | None = Field(default=None, min_length=16, max_length=512)
    password: SecretStr = Field(min_length=1, max_length=256)


class ErpCheckOut(BaseModel):
    """Ответ ERP на `GET /api/integration/v1/health` (схема `Health` контракта) и время ответа."""

    status: Literal["ok", "degraded"]
    version: str
    migrations_applied: bool
    queue_alive: bool
    checked_at: datetime
    latency_ms: int
