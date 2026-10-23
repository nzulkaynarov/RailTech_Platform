"""Миграции 0035–0036 и 0038 (R-1, R-1b): коды `users.platform_roles` -> роли -> столбца нет.

expand -> migrate -> contract: пользователь с `[MANAGER, ACCOUNTANT]` получает две роли с теми же
правами, что до миграции; системные роли и шаблоны вставлены из снимка каталога; сотрудникам с
ролями и доступом к ERP ставится провижининг; downgrade возвращает столбец с кодами.
"""

from pathlib import Path

import psycopg
import pytest
import yaml
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.platform_roles import RoleGrant, default_roles, derive_access
from app.main import create_app
from app.security.passwords import hash_password
from app.security.rbac import Rbac, read_seed
from tests.integration.crm_helpers import PASSWORD
from tests.integration.test_migrations import _seed_user
from tests.platform_role_data import make_role

pytestmark = pytest.mark.integration
REPO = Path(__file__).resolve().parents[5]
CASBIN_DIR = REPO / "apps" / "crm" / "infra" / "casbin"
# Снимок матрицы версии 1 (из контракта удалена в R-2).
V1 = Path(__file__).resolve().parents[1] / "fixtures" / "platform_rbac_v1_matrix.yaml"
BEFORE = "0034_user_language"


def _v1_union(codes: list[str]) -> dict[str, str]:
    """Объединение колонок матрицы версии 1 (максимум по разделу) — права «до миграции»."""
    rank = {"hidden": 0, "read": 1, "full": 2}
    union: dict[str, str] = {}
    for res in yaml.safe_load(V1.read_text(encoding="utf-8"))["resources"]:
        best = max((res["access"][c] for c in codes), key=rank.__getitem__)
        if best != "hidden":
            union[res["key"]] = best
    return union


def _seed(conn: psycopg.Connection) -> dict[str, int]:
    conn.execute("TRUNCATE users, audit_log, procrastinate_jobs RESTART IDENTITY CASCADE")
    both = '["crm", "erp"]'
    seeds = {
        "mgr_acc": ("manager", '["MANAGER", "ACCOUNTANT"]', both),
        "admin": ("admin", '["ADMIN"]', both),
        "dir_sup": ("viewer", '["DIRECTOR", "SUPPLY"]', both),
        "eng_no_erp": ("viewer", '["ENGINEER"]', '["crm"]'),
        "manual": ("manager", "[]", both),
    }
    ids = {
        name: _seed_user(conn, f"{name}@x.uz", role, platform_roles=codes, platform_access=access)
        for name, (role, codes, access) in seeds.items()
    }
    ids["inactive"] = _seed_user(
        conn,
        "off@x.uz",
        "manager",
        platform_roles='["MANAGER"]',
        platform_access=both,
        is_active=False,
    )
    return ids


def _roles_of(conn: psycopg.Connection, user_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT r.code FROM user_platform_roles up JOIN platform_roles r ON r.id = up.role_id "
        "WHERE up.user_id = %s ORDER BY r.id",
        (user_id,),
    ).fetchall()
    return [r[0] for r in rows]


def test_codes_become_roles_the_column_goes_and_downgrade_brings_the_codes_back(
    alembic_config: Config, live_settings: Settings
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, BEFORE)
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        ids = _seed(conn)
        before = conn.execute(
            "SELECT id, platform_access, erp_role_codes, "
            "(SELECT array_agg(r.name ORDER BY r.name) FROM user_roles ur "
            " JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = users.id) "
            "FROM users ORDER BY id"
        ).fetchall()

    command.upgrade(alembic_config, "head")

    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        # Системные роли и шаблоны — снимок каталога; id по порядку вставки.
        roles = conn.execute(
            "SELECT code, name, is_system, access, restricted_fields "
            "FROM platform_roles ORDER BY id"
        ).fetchall()
        assert [
            {"code": c, "name": n, "is_system": s, "access": a, "restricted_fields": f}
            for c, n, s, a, f in roles
        ] == default_roles()
        # Пользователь с [MANAGER, ACCOUNTANT] -> две роли; остальные — по кодам.
        assert _roles_of(conn, ids["mgr_acc"]) == ["tpl:MANAGER", "tpl:ACCOUNTANT"]
        assert _roles_of(conn, ids["admin"]) == ["ADMIN"]
        assert _roles_of(conn, ids["dir_sup"]) == ["DIRECTOR", "tpl:SUPPLY"]
        assert _roles_of(conn, ids["eng_no_erp"]) == ["tpl:ENGINEER"]
        assert _roles_of(conn, ids["manual"]) == []
        assert _roles_of(conn, ids["inactive"]) == ["tpl:MANAGER"]
        # Роли CRM, доступ и роли ERP сотрудников миграция не трогает.
        after = conn.execute(
            "SELECT id, platform_access, erp_role_codes, "
            "(SELECT array_agg(r.name ORDER BY r.name) FROM user_roles ur "
            " JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = users.id) "
            "FROM users ORDER BY id"
        ).fetchall()
        assert after == before
        # Пересчёт прав ERP — активным сотрудникам с ролями и доступом к ERP.
        jobs = conn.execute("SELECT task_name, args FROM procrastinate_jobs ORDER BY id").fetchall()
        # 0035 — всем с ролями; 0038 (R-1b, директор без лидов) — ещё раз держателю «Директора».
        assert jobs == [
            ("erp_provision_user", {"user_id": ids[name]})
            for name in ("mgr_acc", "admin", "dir_sup", "dir_sup")
        ]
        # Директор: лиды и внешние чаты — только чтение, версия роли выросла (0038).
        director = conn.execute(
            "SELECT access, version FROM platform_roles WHERE code = 'DIRECTOR'"
        ).fetchone()
        assert director is not None
        assert (director[0]["crm.leads"], director[0]["chats.external"]) == ("read", "read")
        assert director[1] == 2
        assert conn.execute(
            "SELECT DISTINCT version FROM platform_roles WHERE code <> 'DIRECTOR'"
        ).fetchall() == [(1,)]
        # Столбец с кодами удалён, связь по роли не даёт её удалить.
        columns = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'platform_roles'"
        ).fetchall()
        assert columns == []
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute("DELETE FROM platform_roles WHERE code = 'tpl:MANAGER'")

    command.downgrade(alembic_config, BEFORE)
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        codes: dict[int, list[str]] = dict(
            conn.execute("SELECT id, platform_roles FROM users ORDER BY id").fetchall()
        )
        assert codes[ids["mgr_acc"]] == ["MANAGER", "ACCOUNTANT"]
        assert codes[ids["dir_sup"]] == ["DIRECTOR", "SUPPLY"]
        assert codes[ids["admin"]] == ["ADMIN"]
        assert codes[ids["manual"]] == []
        assert conn.execute("SELECT to_regclass('platform_roles')").fetchone() == (None,)

    command.upgrade(alembic_config, "head")  # повтор без ошибок


def test_a_migrated_manager_and_accountant_keeps_the_same_rights(
    alembic_config: Config, live_settings: Settings
) -> None:
    """Пользователь `[MANAGER, ACCOUNTANT]` до и после миграции: та же роль CRM, та же матрица
    разделов (по версии 1), права CRM не уменьшились, права ERP — как задокументировано в PR."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, BEFORE)
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        user_id = _seed(conn)["mgr_acc"]
        conn.execute(
            "UPDATE users SET password_hash = %s, must_change_password = false WHERE id = %s",
            (hash_password(PASSWORD), user_id),
        )
    seed = read_seed(CASBIN_DIR / "policy.seed.csv")
    crm_before = Rbac.from_rules(CASBIN_DIR, seed).permissions(["manager"])
    # ERP до миграции: шаблоны VIEWER и FINANCE + права поверх (MANAGER: deal.manage;
    # ACCOUNTANT: contract.manage, fulfillment.act).
    erp_before = {
        *("deal.manage", "contract.manage", "fulfillment.act"),
        *("finance.invoice", "finance.payment", "finance.rates"),
        *("quote.view_cost_margin", "data.export"),
    }

    command.upgrade(alembic_config, "head")

    app = create_app(live_settings)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login", json={"email": "mgr_acc@x.uz", "password": PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = client.get("/api/v1/me", headers=headers).json()
        crm_after = client.get("/api/v1/me/permissions", headers=headers).json()["permissions"]

    assert me["roles"] == ["manager"]
    assert "platform_roles" not in me
    assert len(me["platform_role_ids"]) == 2
    roles = [make_role("MANAGER"), make_role("ACCOUNTANT")]
    derived = derive_access(
        [RoleGrant(dict(r.access), tuple(r.restricted_fields), r.code) for r in roles]
    )
    assert derived.crm_role == "manager"
    # Матрица разделов = объединение колонок версии 1.
    assert dict(derived.access) == _v1_union(["MANAGER", "ACCOUNTANT"])
    for resource, actions in crm_before.items():
        for action, allowed in actions.items():
            assert crm_after[resource][action] or not allowed, (resource, action)
    extra = {
        f"{res}:{act}"
        for res, actions in crm_after.items()
        for act, allowed in actions.items()
        if allowed and not crm_before[res][act]
    }
    assert extra == {"spend:read"}  # бухгалтер видит «Сводку по компании» (dashboard.summary)
    erp_after = set(derived.erp_permissions)
    assert erp_after - erp_before == {"contract.sign"}
    assert erp_before - erp_after == {"quote.view_cost_margin"}
