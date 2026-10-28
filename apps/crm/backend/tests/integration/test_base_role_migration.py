"""Миграция «базовая роль CRM по матрице» (D1-8, B-014): признак пересчитан, права не менялись.

Сотрудник с ролями Платформы получает базовую роль по матрице: `admin: full` — admin,
`crm.leads: full` — manager, иначе viewer (раньше роль с кодом задавала признак по коду, и шаблон
«Бухгалтер» был `manager`). Сотрудники без ролей Платформы не затрагиваются; откат возвращает
`manager` держателям шаблона «Бухгалтер».
"""

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from app.config import Settings
from app.domain.platform_roles import default_roles
from tests.integration.test_migrations import _seed_user

pytestmark = pytest.mark.integration
REVISION = "0047_base_role_by_matrix"


def _ensure_roles(conn: psycopg.Connection) -> None:
    """Другие тесты очищают таблицы целиком: системные роли и шаблоны — как после миграции."""
    row = conn.execute("SELECT count(*) FROM platform_roles").fetchone()
    if row is not None and row[0] == 0:
        for role in default_roles():
            conn.execute(
                "INSERT INTO platform_roles (code, name, is_system, access, restricted_fields) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    role["code"],
                    role["name"],
                    role["is_system"],
                    Jsonb(role["access"]),
                    Jsonb(role["restricted_fields"]),
                ),
            )


def _grant(conn: psycopg.Connection, user_id: int, *codes: str) -> None:
    for code in codes:
        conn.execute(
            "INSERT INTO user_platform_roles (user_id, role_id) "
            "SELECT %s, id FROM platform_roles WHERE code = %s",
            (user_id, code),
        )


def _base(conn: psycopg.Connection, user_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
        "WHERE ur.user_id = %s ORDER BY r.name",
        (user_id,),
    ).fetchall()
    return [r[0] for r in rows]


def test_base_roles_follow_the_matrix_and_downgrade_restores_the_accountant(
    alembic_config: Config, live_settings: Settings
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, f"{REVISION}-1")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        # Не TRUNCATE ... CASCADE: он утащил бы и `platform_roles` (внешний ключ `created_by`).
        conn.execute("DELETE FROM users")
        _ensure_roles(conn)
        ids = {
            # как до миграции: бухгалтер по коду — manager
            "accountant": _seed_user(conn, "acc@x.uz", "manager"),
            "accountant_manager": _seed_user(conn, "accman@x.uz", "manager"),
            "manager": _seed_user(conn, "man@x.uz", "manager"),
            "supply": _seed_user(conn, "sup@x.uz", "viewer"),
            "director": _seed_user(conn, "dir@x.uz", "viewer"),
            "admin": _seed_user(conn, "adm@x.uz", "admin"),
            "legacy": _seed_user(conn, "old@x.uz", "manager"),  # без ролей Платформы
        }
        _grant(conn, ids["accountant"], "tpl:ACCOUNTANT")
        _grant(conn, ids["accountant_manager"], "tpl:ACCOUNTANT", "tpl:MANAGER")
        _grant(conn, ids["manager"], "tpl:MANAGER")
        _grant(conn, ids["supply"], "tpl:SUPPLY")
        _grant(conn, ids["director"], "DIRECTOR")
        _grant(conn, ids["admin"], "ADMIN", "DIRECTOR")

    command.upgrade(alembic_config, REVISION)

    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert _base(conn, ids["accountant"]) == ["viewer"]
        assert _base(conn, ids["accountant_manager"]) == ["manager"]
        assert _base(conn, ids["manager"]) == ["manager"]
        assert _base(conn, ids["supply"]) == ["viewer"]
        assert _base(conn, ids["director"]) == ["viewer"]
        assert _base(conn, ids["admin"]) == ["admin"]
        assert _base(conn, ids["legacy"]) == ["manager"], "без ролей Платформы — как было"

    command.upgrade(alembic_config, REVISION)  # повтор без изменений
    command.downgrade(alembic_config, f"{REVISION}-1")

    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert _base(conn, ids["accountant"]) == ["manager"]
        assert _base(conn, ids["supply"]) == ["viewer"]
        assert _base(conn, ids["legacy"]) == ["manager"]
    command.upgrade(alembic_config, "head")
