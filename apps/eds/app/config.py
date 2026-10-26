"""Настройки сервиса — единственное место чтения переменных окружения.

Значения приходят из env (в контейнерах — из `.env` через compose). Остальной код получает
настройки только через `get_settings()`. Переменные шины `RT_BUS_*` читает сама библиотека `rt_bus`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    app_env: Literal["dev", "prod", "test"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # postgresql+psycopg://<роль>:<пароль>@<хост>:5432/eds (прод: роль eds_app, `?sslmode=require`).
    database_url: SecretStr = Field(validation_alias="EDS_DATABASE_URL")
    # Секрет токена доступа EDS (HS256, 15 минут): токен выпускает обмен SSO-токена, проверяет каждый запрос.
    access_secret: SecretStr = Field(validation_alias="EDS_ACCESS_SECRET", min_length=32)
    # Общий секрет SSO-токена сотрудника CRM; ротация — два значения через запятую (docs/architecture/sso-token.md).
    platform_sso_secret: SecretStr = Field(validation_alias="PLATFORM_SSO_SECRET")

    # Хранилище файлов (RustFS): отдельный ключ сервиса с доступом только к бакету eds-private (S0-9).
    # Файлы документов (домен, E3): ключ `files/<id>/v<версия>`, чтение потоком (`app/services/storage.py`).
    s3_endpoint: AnyHttpUrl = AnyHttpUrl("http://rustfs:9000")
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_region: str = "us-east-1"
    s3_bucket: str = "eds-private"

    # Задач очереди одновременно в одном воркере: pump шины держит воркер до 20 с, пока подписчик не отвечает.
    worker_concurrency: int = Field(default=4, ge=1, le=32)
    health_timeout_s: float = Field(default=2.0, gt=0, le=10)
    version: str = Field(default="dev", validation_alias="EDS_VERSION")

    @field_validator("platform_sso_secret")
    @classmethod
    def _sso_secret_not_empty(cls, value: SecretStr) -> SecretStr:
        parts = [part.strip() for part in value.get_secret_value().split(",") if part.strip()]
        if not parts:
            raise ValueError("PLATFORM_SSO_SECRET must hold at least one non-empty secret")
        if any(len(part) < MIN_SECRET_LENGTH for part in parts):
            raise ValueError(f"PLATFORM_SSO_SECRET: every secret must be at least {MIN_SECRET_LENGTH} characters")
        return value

    @property
    def sso_secrets(self) -> list[str]:
        """Действующие секреты SSO-токена: оба значения при ротации принимаются."""
        return [p.strip() for p in self.platform_sso_secret.get_secret_value().split(",") if p.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """DSN для SQLAlchemy (async, драйвер psycopg 3)."""
        return _with_scheme(self.database_url.get_secret_value(), "postgresql+psycopg")

    @property
    def libpq_dsn(self) -> str:
        """DSN в формате libpq — для Procrastinate."""
        return _with_scheme(self.database_url.get_secret_value(), "postgresql")


def _with_scheme(url: str, scheme: str) -> str:
    rest = url.split("://", 1)[1] if "://" in url else url
    return f"{scheme}://{rest}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # обязательные поля приходят из окружения
