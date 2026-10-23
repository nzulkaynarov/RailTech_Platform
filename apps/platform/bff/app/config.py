"""Настройки BFF из переменных окружения (секретов здесь нет: сессия — случайный id в Redis)."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    crm_url: str = Field(
        default="http://crm-api:8000", validation_alias=AliasChoices("PLATFORM_CRM_URL")
    )
    erp_url: str = Field(
        default="http://erp-backend:8000", validation_alias=AliasChoices("PLATFORM_ERP_URL")
    )
    redis_url: str = Field(
        default="redis://redis:6379/0", validation_alias=AliasChoices("REDIS_URL")
    )
    # Абсолютное время жизни сессии сотрудника в Redis (часы), от входа.
    session_ttl_hours: int = Field(
        default=12, ge=1, validation_alias=AliasChoices("PLATFORM_SESSION_TTL_HOURS")
    )
    # Secure у cookie сессии. Выключается только для разработки по http (`uv run` без Caddy).
    cookie_secure: bool = Field(
        default=True, validation_alias=AliasChoices("PLATFORM_COOKIE_SECURE")
    )
    # Имя cookie с refresh-токеном ERP (`REFRESH_COOKIE_NAME` ERP); у CRM — `rt_refresh`.
    erp_refresh_cookie: str = Field(
        default="refresh_token", validation_alias=AliasChoices("PLATFORM_ERP_REFRESH_COOKIE")
    )
    # Лимит попыток входа в минуту — отдельно на IP и на e-mail (platform-bff.yaml, «Лимиты»).
    login_rate_per_minute: int = Field(
        default=10, ge=1, validation_alias=AliasChoices("PLATFORM_LOGIN_RATE_PER_MINUTE")
    )
    # Поток подсказок (SSE, B5): окно слияния всплеска (мс), период heartbeat-комментария (с).
    events_coalesce_ms: int = Field(
        default=300, ge=0, le=2000, validation_alias=AliasChoices("PLATFORM_EVENTS_COALESCE_MS")
    )
    events_heartbeat_seconds: float = Field(
        default=20.0, gt=0, validation_alias=AliasChoices("PLATFORM_EVENTS_HEARTBEAT_SECONDS")
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias=AliasChoices("LOG_LEVEL")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
