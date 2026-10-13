"""Настройки приложения — единственное место чтения переменных окружения.

Значения приходят из env (в контейнерах — из `.env` через compose). Описание
каждой переменной — в `.env.example`. Остальной код получает настройки только
через `get_settings()`.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_casbin_dir() -> Path:
    """В контейнере — `/app/casbin` (volume из `infra/casbin`), локально — из репозитория."""
    repo = Path(__file__).resolve().parents[2] / "infra" / "casbin"
    return repo if repo.is_dir() else Path("/app/casbin")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["dev", "prod", "test"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "railtech"
    postgres_user: str = "railtech"
    postgres_password: SecretStr = SecretStr("")

    s3_endpoint: AnyHttpUrl = AnyHttpUrl("http://rustfs:9000")
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_region: str = "us-east-1"
    s3_bucket_kb: str = "kb-sources"
    s3_bucket_documents: str = "client-documents"
    s3_bucket_attachments: str = "tg-attachments"

    litellm_base_url: AnyHttpUrl = AnyHttpUrl("http://litellm:4000")
    litellm_api_key: SecretStr = SecretStr("")
    # Модели ролей по умолчанию (ADR-0020): засев БД LiteLLM и «Сбросить» в «Модели ИИ».
    litellm_models_path: Path = Path("/app/litellm.models.yaml")
    llm_timeout_s: float = Field(default=20.0, gt=0)
    # Пометка вызовов в учёте расходов (`llm_usage.kind`): `test` ставят make eval/load-test.
    llm_usage_kind: Literal["work", "test"] = "work"

    docling_url: AnyHttpUrl = AnyHttpUrl("http://docling:5001")
    docling_api_key: SecretStr = SecretStr("")
    docling_timeout_s: float = Field(default=300.0, gt=0)

    telegram_bot_token: SecretStr = SecretStr("")
    telegram_mode: Literal["polling", "webhook", "disabled"] = "polling"
    telegram_webhook_url: str = ""
    telegram_webhook_secret: SecretStr = SecretStr("")
    # Только e2e/демо без Telegram: исходящие сообщения лиду пишутся в лог, а не отправляются.
    telegram_dry_run: bool = False

    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: AnyHttpUrl = AnyHttpUrl("http://langfuse-web:3000")

    agent_context_key: SecretStr = SecretStr("")
    kb_mcp_url: AnyHttpUrl = AnyHttpUrl("http://kb-mcp:8101/mcp")
    crm_mcp_url: AnyHttpUrl = AnyHttpUrl("http://crm-mcp:8102/mcp")
    docs_mcp_url: AnyHttpUrl = AnyHttpUrl("http://docs-mcp:8103/mcp")

    ready_check_timeout_s: float = Field(default=2.0, gt=0, le=10)

    # Ключ Fernet для секретов интеграций в БД (токен бота из «Подключений»). Без него — только env.
    secrets_key: SecretStr = SecretStr("")

    # Коннектор «ERP» (ADR-0022, M3-CRM-02): пусто — коннектор не настроен, жизненный цикл в режиме
    # `local`. Адрес и секреты из «Подключений» (БД) имеют приоритет над env, как у бота (ADR-0018).
    # `erp_base_url` — корень ERP (`https://erp.example.com`); `/api/integration/v1` добавляет код.
    erp_base_url: str = ""
    erp_service_token: SecretStr = SecretStr("")
    # Секрет подписи вебхуков ERP → CRM (CONTRACTS §3, `X-Signature`); приёмник — M3-CRM-04.
    erp_webhook_secret: SecretStr = SecretStr("")

    jwt_secret: SecretStr = SecretStr("")
    access_token_ttl_s: int = Field(default=900, ge=60)
    refresh_token_ttl_days: int = Field(default=30, ge=1)
    login_max_failures: int = Field(default=10, ge=3)
    login_lockout_minutes: int = Field(default=15, ge=1)
    casbin_dir: Path = Field(default_factory=_default_casbin_dir)
    # Том бэкапов (ADR-0013), api смонтирован в него: список копий и запрос «сделать сейчас».
    backup_dir: Path = Path("/backups")

    def _postgres_dsn(self, scheme: str) -> str:
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password.get_secret_value(), safe="")
        return (
            f"{scheme}://{user}:{password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "prod"

    @property
    def agent_context_key_bytes(self) -> bytes:
        return self.agent_context_key.get_secret_value().encode("utf-8")

    @property
    def sqlalchemy_url(self) -> str:
        """DSN для SQLAlchemy (async, драйвер psycopg 3)."""
        return self._postgres_dsn("postgresql+psycopg")

    @property
    def libpq_dsn(self) -> str:
        """DSN в формате libpq — для Procrastinate и psql."""
        return self._postgres_dsn("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
