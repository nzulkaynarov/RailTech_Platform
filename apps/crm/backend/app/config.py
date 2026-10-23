"""Настройки приложения — единственное место чтения переменных окружения.

Значения приходят из env (в контейнерах — из `.env` через compose). Описание
каждой переменной — в `.env.example`. Остальной код получает настройки только
через `get_settings()`.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
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
    # Бакет, куда бэкап VPS 2 выгружает дампы (`infra/db/backup.sh`, BACKUP_RUSTFS_BUCKET).
    s3_bucket_backups: str = "backups"

    litellm_base_url: AnyHttpUrl = AnyHttpUrl("http://litellm:4000")
    litellm_api_key: SecretStr = SecretStr("")
    # Модели ролей по умолчанию (ADR-0020): засев БД LiteLLM и «Сбросить» в «Модели ИИ».
    litellm_models_path: Path = Path("/app/litellm.models.yaml")
    llm_timeout_s: float = Field(default=20.0, gt=0)
    # Пометка вызовов в учёте расходов (`llm_usage.kind`): `test` ставят make eval/load-test.
    llm_usage_kind: Literal["work", "test"] = "work"

    # Пустой `DOCLING_URL` — «docling на этом сервере не используется» (прод, M5-CRM-02):
    # md/txt индексируются встроенным конвертером, остальные форматы отклоняются.
    docling_url: AnyHttpUrl | None = AnyHttpUrl("http://docling:5001")
    docling_api_key: SecretStr = SecretStr("")
    docling_timeout_s: float = Field(default=300.0, gt=0)

    telegram_bot_token: SecretStr = SecretStr("")
    telegram_mode: Literal["polling", "webhook", "disabled"] = "polling"
    telegram_webhook_url: str = ""
    telegram_webhook_secret: SecretStr = SecretStr("")
    # Только e2e/демо без Telegram: исходящие сообщения лиду пишутся в лог, а не отправляются.
    telegram_dry_run: bool = False
    # Адрес Bot API: пусто — официальный `https://api.telegram.org`. Свой сервер Bot API или
    # заглушка на стенде (S0-4: проверка crm-bot без токена); значение токена в адрес не входит.
    telegram_api_base_url: str = ""
    # Процесс бота (`python -m app bot`, S0-4): как часто он смотрит в БД, не просил ли `crm-api`
    # перезапуск (смена токена в «Подключениях»); как часто пишет пульс; через сколько секунд без
    # пульса «Состояние системы» считает процесс недоступным; пауза между попытками поднять бота.
    bot_poll_interval_s: float = Field(default=2.0, gt=0)
    bot_heartbeat_s: float = Field(default=10.0, gt=0)
    bot_stale_after_s: float = Field(default=45.0, gt=0)
    bot_retry_s: float = Field(default=30.0, gt=0)
    # Сколько `crm-api` ждёт, пока `crm-bot` применит смену токена, прежде чем ответить админу.
    bot_restart_wait_s: float = Field(default=10.0, ge=0)

    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: AnyHttpUrl = AnyHttpUrl("http://langfuse-web:3000")

    agent_context_key: SecretStr = SecretStr("")
    kb_mcp_url: AnyHttpUrl = AnyHttpUrl("http://kb-mcp:8101/mcp")
    crm_mcp_url: AnyHttpUrl = AnyHttpUrl("http://crm-mcp:8102/mcp")
    docs_mcp_url: AnyHttpUrl = AnyHttpUrl("http://docs-mcp:8103/mcp")
    # Сервисный режим бота (M3-CRM-07): инструменты ERP через `erp-mcp` (CONTRACTS §5). Выключено —
    # бот отвечает клиенту без данных ERP; включено — нужен `ERP_MCP_CONTEXT_KEY`, общий с ERP.
    erp_mcp_enabled: bool = False
    erp_mcp_url: AnyHttpUrl = AnyHttpUrl("http://erp-mcp:8104/mcp/erp")
    erp_mcp_context_key: SecretStr = SecretStr("")

    ready_check_timeout_s: float = Field(default=2.0, gt=0, le=10)
    # Задач очереди одновременно в одном воркере. Больше 1 нужно шине: `rt_bus.pump` держит воркер
    # до 20 с, пока ERP не отвечает; без запаса остальные задачи (бот, таймеры) ждали бы.
    worker_concurrency: int = Field(default=4, ge=1, le=32)

    # Ключ Fernet для секретов интеграций в БД (токен бота из «Подключений»). Без него — только env.
    secrets_key: SecretStr = SecretStr("")

    # Коннектор «ERP» (ADR-0022, M3-CRM-02): пусто — коннектор не настроен, жизненный цикл в режиме
    # `local`. Адрес и секреты из «Подключений» (БД) имеют приоритет над env, как у бота (ADR-0018).
    # `erp_base_url` — корень ERP во внутренней сети (`http://erp-backend:8000`); путь
    # `/api/integration/v1` добавляет код.
    erp_base_url: str = ""
    erp_service_token: SecretStr = SecretStr("")
    # Секрет подписи вебхуков ERP → CRM (CONTRACTS §3, `X-Signature`); приёмник — M3-CRM-04.
    erp_webhook_secret: SecretStr = SecretStr("")
    # Подпись вебхуков — только v2 (FIX-61); старая (HMAC только тела) отключена (S0-5).

    # Коннектор «Почта» (M3-CRM-08, ADR-0018): SMTP-релей для писем сотрудникам (приглашение,
    # сброс пароля). Запасной источник: настройки из «Подключений» → «Почта» имеют приоритет.
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from_email: str = ""
    smtp_from_name: str = ""
    # Origin страницы входа Cabinet, откуда вызывается публичная форма «Запрос»
    # (`POST /api/v1/leads/web`, M3-CRM-05): `https://cabinet.railtech.uz`; несколько — через
    # запятую. Пусто — CORS для формы не включён (только same-origin).
    cabinet_origin: str = ""

    # Платформенный SSO-секрет (CRM ↔ ERP, CONTRACTS §6, M3-CRM-06): HS256, поддержка ротации.
    platform_sso_secret: SecretStr = SecretStr("")
    # Переход CRM ↔ ERP выключен до волны 1 исправлений (FIX-03, аудит S-2/S-3): сейчас обмен
    # токена небезопасен. Включает владелец после FIX-10/FIX-11.
    platform_sso_enabled: bool = False
    erp_frontend_url: str = "http://erp.localhost"

    jwt_secret: SecretStr = SecretStr("")
    access_token_ttl_s: int = Field(default=900, ge=60)
    refresh_token_ttl_days: int = Field(default=30, ge=1)
    login_max_failures: int = Field(default=10, ge=3)
    login_lockout_minutes: int = Field(default=15, ge=1)
    casbin_dir: Path = Field(default_factory=_default_casbin_dir)
    # Том бэкапов (ADR-0013), api смонтирован в него: список копий и запрос «сделать сейчас».
    backup_dir: Path = Path("/backups")
    # Откуда CRM берёт статус бэкапов (M5-CRM-01): `volume` — том backup-контейнера (dev),
    # `rustfs` — бакет `backups`, куда пишет VPS 2 (прод), `auto` — том, если он смонтирован
    # в api, иначе бакет. Переменная BACKUP_SOURCE; на стенде и в проде менять не нужно.
    backup_source: Literal["auto", "volume", "rustfs"] = "auto"

    def _postgres_dsn(self, scheme: str) -> str:
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password.get_secret_value(), safe="")
        return (
            f"{scheme}://{user}:{password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    @field_validator("docling_url", mode="before")
    @classmethod
    def _blank_docling_url_is_off(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _prod_requires_seam_secrets(self) -> "Settings":
        """Ключа SSO по умолчанию нет (FIX-01): prod без него не стартует, иначе SSO выключен."""
        if self.app_env == "prod" and not self.platform_sso_secrets:
            raise ValueError("PLATFORM_SSO_SECRET is required when APP_ENV=prod")
        return self

    @property
    def backup_source_resolved(self) -> Literal["volume", "rustfs"]:
        if self.backup_source != "auto":
            return self.backup_source
        if self.backup_dir.is_dir() or self.app_env != "prod":
            return "volume"
        return "rustfs"

    @property
    def platform_sso_secrets(self) -> list[str]:
        """Список активных ключей SSO для ротации (первый — для подписи новых)."""
        raw = self.platform_sso_secret.get_secret_value()
        return [k.strip() for k in raw.split(",") if k.strip()]

    @property
    def cabinet_origins(self) -> list[str]:
        """Разрешённые origin формы «Запрос» без завершающего `/`."""
        return [o.strip().rstrip("/") for o in self.cabinet_origin.split(",") if o.strip()]

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "prod"

    @property
    def agent_context_key_bytes(self) -> bytes:
        return self.agent_context_key.get_secret_value().encode("utf-8")

    @property
    def erp_mcp_context_key_bytes(self) -> bytes:
        return self.erp_mcp_context_key.get_secret_value().encode("utf-8")

    @property
    def erp_mcp_ready(self) -> bool:
        """Бот пользуется `erp-mcp` только при включённом флаге и заданном ключе контекста."""
        return self.erp_mcp_enabled and bool(self.erp_mcp_context_key.get_secret_value())

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
