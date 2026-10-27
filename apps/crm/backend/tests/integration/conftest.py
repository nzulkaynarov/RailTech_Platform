"""Integration-тесты: реальные Postgres (+pgvector) и RustFS (S3).

В CI это service containers (`.github/workflows/ci.yml`); параметры подключения
передаются через те же переменные окружения, что и в приложении.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from psycopg import sql
from psycopg.conninfo import make_conninfo
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import db
from app.config import Settings, get_settings
from app.domain.platform_roles import default_roles
from app.security import passwords
from app.tasks.queue import queue

ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"
AGENT_KEY = "integration-agent-context-key-0123456789"
TABLES = (
    "bot_runtime",
    "kb_chunks",
    "kb_documents",
    "kb_gaps",
    "products",
    "deals",
    "leads",
    "telegram_identities",
    "conversations",
    "messages",
    "tg_updates",
    "lead_notes",
    "settings",
    "qualifier_runs",
    "escalations",
    "stage_transitions",
    "users",
    "audit_log",
    "refresh_tokens",
    "clients",
    "client_contacts",
    "documents",
    "document_access_log",
    "service_requests",
    "system_alerts",
    "integration_secrets",
    "telegram_chat_candidates",
    "llm_usage",
    "email_log",
    "sso_replay_tokens",
    "erp_event_notices",
    "rt_bus_outbox",
    "rt_bus_delivery",
    "rt_bus_inbox",
    "rt_bus_subscriber_state",
    "external_service_checks",
    "external_service_incidents",
    "external_service_switches",
    "procrastinate_jobs",
    "platform_roles",
    "identity_catalog_state",
)
FAKE_KEY = "x" * 40  # фиктивный ключ только для тестов


async def reseed_platform_roles(session: AsyncSession) -> None:
    """Системные роли и шаблоны как после миграции (id 1..6), чтобы тесты не мешали друг другу."""
    insert = text(
        "INSERT INTO platform_roles "
        "(code, name, description, is_system, access, restricted_fields) "
        "VALUES (:code, :name, '', :is_system, CAST(:access AS jsonb), CAST(:fields AS jsonb))"
    )
    for row in default_roles():
        await session.execute(
            insert,
            {
                "code": row["code"],
                "name": row["name"],
                "is_system": row["is_system"],
                "access": json.dumps(row["access"]),
                "fields": json.dumps(row["restricted_fields"]),
            },
        )


@pytest.fixture(scope="session", autouse=True)
def _worker_database() -> None:
    """Параллельный прогон (pytest-xdist): у каждого воркера своя база `<БД>_gwN` на том же сервере.

    Тесты делают TRUNCATE всех таблиц, поэтому делить одну базу воркеры не могут. Имя базы
    подставляет `tests/conftest.py` в POSTGRES_DB при старте воркера — до первого чтения настроек и
    до импорта `app.tasks.queue` (очередь Procrastinate берёт DSN при импорте). Здесь база создаётся
    при первом обращении; повторные прогоны на тех же контейнерах её переиспользуют (миграции
    идемпотентны). Без xdist — ничего не меняется: одна база из окружения, как в CI.
    """
    if os.environ.get("PYTEST_XDIST_WORKER") is None:
        return
    settings = Settings(_env_file=None)
    name = settings.postgres_db
    maintenance = make_conninfo(settings.libpq_dsn, dbname="postgres")
    with psycopg.connect(maintenance, autocommit=True) as conn:
        found = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if found is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    # Очередь и настройки обязаны смотреть в базу воркера, а не в общую: иначе задачи Procrastinate
    # разных воркеров делят одну procrastinate_jobs (а в чистом CI в общей базе её и нет).
    assert get_settings().postgres_db == name
    assert queue.connector._pool_args["conninfo"].endswith(f"/{name}")  # type: ignore[attr-defined]


@pytest.fixture(scope="session", autouse=True)
def _cheap_password_hasher() -> Iterator[None]:
    """argon2id с боевыми параметрами (64 МиБ, ~60 мс) тратит больше половины времени тестов, где
    пользователя создают и входят заново на каждый тест. Здесь параметры минимальные; формат хеша,
    проверка и отказ при неверном пароле те же (параметры хранятся в самом хеше)."""
    patch = pytest.MonkeyPatch()
    patch.setattr(passwords, "_HASHER", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    yield
    patch.undo()


@pytest.fixture(scope="session", autouse=True)
def _drain_wakeups_of_own_loop_only() -> Iterator[None]:
    """Пробуждения шины ставятся на цикл, где прошёл коммит, а `TestClient` гасит приложение в
    своём цикле: `asyncio.gather` задачи чужого цикла падает с «attached to a different loop», если
    задача ещё не успела завершиться (гонка по времени; быстрее тесты — чаще). Пробуждение — лишь
    ускорение доставки (периодический проход подберёт событие), поэтому дожидаемся только задач
    своего цикла, как в `test_bus_wakeup`; чужие не трогаем."""
    original = AsyncBus.drain_wakeups

    async def drain_wakeups(self: AsyncBus) -> None:
        loop = asyncio.get_running_loop()
        own = [task for task in self._wake_tasks if task.get_loop() is loop]
        if own:
            await asyncio.gather(*own, return_exceptions=True)

    patch = pytest.MonkeyPatch()
    patch.setattr(AsyncBus, "drain_wakeups", drain_wakeups)
    yield
    patch.undo()
    assert AsyncBus.drain_wakeups is original


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    return Settings(
        _env_file=None, app_env="test", agent_context_key=AGENT_KEY, jwt_secret=FAKE_KEY
    )


@pytest.fixture
def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


@pytest.fixture
def migrated_db(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")


@pytest.fixture
async def sessions(
    migrated_db: None, live_settings: Settings
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = db.create_engine(live_settings)
    factory = db.create_session_factory(engine)
    async with factory() as session, session.begin():
        await session.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        await session.execute(text("DELETE FROM casbin_rule WHERE v0 LIKE 'pr:%'"))
        await reseed_platform_roles(session)
    yield factory
    await engine.dispose()
