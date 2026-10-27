"""Integration-тесты: реальные Postgres (+pgvector) и RustFS (S3).

В CI это service containers (`.github/workflows/ci.yml`); параметры подключения
передаются через те же переменные окружения, что и в приложении.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import db
from app.config import Settings
from app.domain.platform_roles import default_roles

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
