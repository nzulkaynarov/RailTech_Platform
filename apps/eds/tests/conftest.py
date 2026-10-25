"""Фикстуры тестов EDS.

Окружение выставляется ДО импорта приложения (настройки читаются при импорте очереди): `APP_ENV=test`, секреты —
тестовые, база — `eds_test` на сервере `EDS_TEST_DATABASE_URL` (задаёт `scripts/with_pg.sh`). Тесты с маркером `pg`
пересоздают базу один раз за сессию, применяют миграции Alembic и перед каждым тестом чистят таблицы.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql as psql

_ADMIN_URL = os.environ.get("EDS_TEST_DATABASE_URL", "")
_DB_NAME = "eds_test"
_APP_ROOT = Path(__file__).resolve().parents[1]


def _fake_secret(label: str) -> str:
    """Тестовый секрет ≥ 32 байт (короче HS256-ключ PyJWT считает небезопасным); собирается кодом, не литералом."""
    return f"{label}-".ljust(40, "x")


ACCESS_SECRET = _fake_secret("test-access")
SSO_CURRENT = _fake_secret("test-sso-current")
SSO_PREVIOUS = _fake_secret("test-sso-previous")
BUS_SECRET_CRM_EDS = _fake_secret("test-bus-crm-eds")
BUS_SECRET_ERP_EDS = _fake_secret("test-bus-erp-eds")
BUS_SECRET_UNRELATED = _fake_secret("unrelated-pair")

os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["EDS_ACCESS_SECRET"] = ACCESS_SECRET
os.environ["PLATFORM_SSO_SECRET"] = f"{SSO_CURRENT},{SSO_PREVIOUS}"
os.environ["RT_BUS_SECRET_CRM_EDS"] = BUS_SECRET_CRM_EDS
os.environ["RT_BUS_SECRET_ERP_EDS"] = BUS_SECRET_ERP_EDS
if _ADMIN_URL:
    _head = _ADMIN_URL.rpartition("/")[0]
    os.environ["EDS_DATABASE_URL"] = f"{_head}/{_DB_NAME}".replace("postgresql://", "postgresql+psycopg://", 1)
else:
    os.environ["EDS_DATABASE_URL"] = "postgresql+psycopg://nobody:nobody@127.0.0.1:1/none"

from app.config import Settings, get_settings  # noqa: E402
from app.container import Container  # noqa: E402
from app.main import create_app  # noqa: E402


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _ADMIN_URL:
        return
    marker = pytest.mark.skip(reason="нет EDS_TEST_DATABASE_URL — запускайте через `make test` (scripts/with_pg.sh)")
    selected_pg = [i for i in items if "pg" in i.keywords]
    if selected_pg and not config.getoption("-m", default=""):
        # Без базы и без явного `-m "not pg"` молчаливый пропуск был бы ложной зеленью.
        raise pytest.UsageError("тесты pg требуют PostgreSQL: `make test` или `make test-unit` (без базы)")
    for item in selected_pg:
        item.add_marker(marker)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def database() -> str:
    """Пересоздаёт `eds_test`, применяет миграции до head; отдаёт URL администратора сервера."""
    with psycopg.connect(_ADMIN_URL, autocommit=True) as conn:
        conn.execute(psql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(psql.Identifier(_DB_NAME)))
        conn.execute(psql.SQL("CREATE DATABASE {}").format(psql.Identifier(_DB_NAME)))
    command.upgrade(alembic_config(), "head")
    return _ADMIN_URL


def alembic_config() -> Config:
    return Config(str(_APP_ROOT / "alembic.ini"))


@pytest.fixture(autouse=True)
def _pg_database(request: pytest.FixtureRequest) -> None:
    """Базу поднимает синхронная фикстура: Alembic вызывает `asyncio.run`, внутри цикла событий это невозможно."""
    if "pg" in request.keywords:
        request.getfixturevalue("database")


@pytest.fixture
async def container(request: pytest.FixtureRequest, settings: Settings) -> AsyncIterator[Container]:
    if "pg" in request.keywords:
        await _truncate(settings)
    box = Container(settings)
    yield box
    await box.aclose()


async def _truncate(settings: Settings) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.sqlalchemy_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE employees, sso_jti, rt_bus_outbox, rt_bus_delivery, rt_bus_inbox, "
                "rt_bus_subscriber_state RESTART IDENTITY"
            )
        )
    await engine.dispose()


@pytest.fixture
async def client(settings: Settings, container: Container) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клиент к приложению в памяти; lifespan выполняется (контейнер, очередь в тестах не открывается)."""
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eds.test") as http,
    ):
        yield http


def user_snapshot(crm_user_id: int = 7, **changes: Any) -> dict[str, Any]:
    """`data.user` события identity по контракту (с `permissions.eds`, как после E1)."""
    user: dict[str, Any] = {
        "crm_user_id": crm_user_id,
        "email": "aliya.karimova@example.com",
        "full_name": "Алия Каримова",
        "position": "Менеджер по продажам",
        "language": "ru",
        "is_active": True,
        "platform_roles": ["MANAGER"],
        "systems": ["crm"],
        "erp_role_codes": [],
        "permissions": {"eds": ["letters.read", "registry.read"]},
        "updated_at": datetime(2026, 10, 26, 8, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
    }
    user.update(changes)
    return user
