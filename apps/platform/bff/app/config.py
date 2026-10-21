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
    # Время жизни сессии сотрудника в Redis (часы). Используется с входом (фаза P1).
    session_ttl_hours: int = Field(
        default=12, ge=1, validation_alias=AliasChoices("PLATFORM_SESSION_TTL_HOURS")
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias=AliasChoices("LOG_LEVEL")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
