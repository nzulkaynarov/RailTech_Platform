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
        # Директор: лиды и внешние чаты — чтение (0038), «Счета и оплаты» — чтение (0049, D2-4),
        # регистрация входящих отдельным разделом (P8); версия роли выросла трижды.
        director = conn.execute(
            "SELECT access, version FROM platform_roles WHERE code = 'DIRECTOR'"
        ).fetchone()
        assert director is not None
        assert (director[0]["crm.leads"], director[0]["chats.external"]) == ("read", "read")
        assert director[0]["eds.payments"] == "read"
        assert director[0]["eds.inbox.register"] == "full"
        # 0.3 (FR-10): + `crm.mail: read` — вся очередь «Почты» без действий (версия 5).
        assert director[0]["crm.mail"] == "read"
        assert director[1] == 5
        # Остальные роли — версия 1; «Бухгалтер» — 2 (0044: без цен поставщиков, D2-1);
        # «Делопроизводитель» — 2 (D17G-1: разбор и передача лидов вместо `crm.leads: full`);
        # «Администратор» — 2 (SIGN-2: реестр полномочий подписи `eds.signing.manage: full`);
        # «Менеджер» и «Снабженец» — 2 (0.3: расчёт менеджеру, снабженцу — без клиентов CRM).
        twice = ["ADMIN", "tpl:ACCOUNTANT", "tpl:REGISTRAR", "tpl:MANAGER", "tpl:SUPPLY"]
        assert conn.execute(
            "SELECT DISTINCT version FROM platform_roles WHERE NOT (code = ANY(%s))",
            (["DIRECTOR", *twice],),
        ).fetchall() == [(1,)]
        assert conn.execute(
            "SELECT DISTINCT version FROM platform_roles WHERE code = ANY(%s)", (twice,)
        ).fetchall() == [(2,)]
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
    # Матрица разделов = объединение колонок версии 1; 0.3 (FR-7): у менеджера расчёт — `full`.
    assert dict(derived.access) == {**_v1_union(["MANAGER", "ACCOUNTANT"]), "erp.calc": "full"}
    for resource, actions in crm_before.items():
        for action, allowed in actions.items():
            assert crm_after[resource][action] or not allowed, (resource, action)
    extra = {
        f"{res}:{act}"
        for res, actions in crm_after.items()
        for act, allowed in actions.items()
        if allowed and not crm_before[res][act]
    }
    # Бухгалтер видит «Сводку по компании» (dashboard.summary); переписка с клиентами — отдельным
    # правом `chats:*` и зоной «Счета и оплаты» (B-D18-1), не правами реестра лидов.
    chats = {"chats:read", "chats:reply", "chats:note", "chats:assist", "chats:invoiced"}
    assert extra == {"spend:read", *chats}
    erp_after = set(derived.erp_permissions)
    # quote.send — менеджер отправляет одобренное КП клиенту (C1-G-4, архитектор 2026-10-26)
    # finance.view — чтение счетов и оплат без права действовать (Q-D2-4-1 п. 2, D2-4)
    # 0.3 (FR-7): менеджер ведёт расчёт — `erp.calc: full` даёт сборку и цены клиенту
    assert erp_after - erp_before == {
        "contract.sign",
        "quote.send",
        "finance.view",
        "quote.build",
        "quote.edit_pricing",
    }
    assert erp_before - erp_after == {"quote.view_cost_margin"}


def test_accountant_template_loses_supplier_prices_and_downgrade_returns_them(
    alembic_config: Config, live_settings: Settings
) -> None:
    """0047 (D2-1, Q-D2-1-4): «Бухгалтер» без цен поставщиков; версия роли растёт в обе стороны."""

    def accountant() -> tuple[list[str], int]:
        with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
            row = conn.execute(
                "SELECT restricted_fields, version FROM platform_roles "
                "WHERE code = 'tpl:ACCOUNTANT'"
            ).fetchone()
        assert row is not None
        return list(row[0]), int(row[1])

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0046_client_requests")
    fields, version = accountant()
    assert "supplier_prices" in fields

    command.upgrade(alembic_config, "head")
    after, after_version = accountant()
    assert after == ["totals_only"]
    assert after_version == version + 1

    command.upgrade(alembic_config, "head")  # повтор — без изменений
    assert accountant() == (after, after_version)


def test_director_reads_payments_and_downgrade_returns_full(
    alembic_config: Config, live_settings: Settings
) -> None:
    """0049 (D2-4, Q-D2-4-1 п. 1): у «Директора» `eds.payments` — `read`, версия растёт."""

    def director() -> tuple[str, int]:
        with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
            row = conn.execute(
                "SELECT access->>'eds.payments', version FROM platform_roles "
                "WHERE code = 'DIRECTOR'"
            ).fetchone()
        assert row is not None
        return str(row[0]), int(row[1])

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "aa1221ec032b")
    level, version = director()
    assert level == "full"

    command.upgrade(alembic_config, "0049_director_payments_read")
    assert director() == ("read", version + 1)

    command.upgrade(alembic_config, "head")  # дальше 0049 раздел не меняется (P8 растит версию)
    assert director()[0] == "read"


def test_pilot_roles_appear_and_the_resolution_holders_keep_registering(
    alembic_config: Config, live_settings: Settings
) -> None:
    """P8: шаблоны пилота вставлены как обычные роли; держатели `eds.inbox: full` получили
    `eds.inbox.register: full`; роль, заведённая администратором с тем же именем, не трогается;
    downgrade снимает раздел и удаляет невыданные роли пилота."""
    before = "ac71231f330f"
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, before)
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT count(*) FROM platform_roles WHERE code IN ('tpl:REGISTRAR', 'tpl:MANAGER_ALL')"
        ).fetchone() == (0,)
        # Своя роль администратора с резолюцией и своя «Менеджер-универсал» без кода.
        conn.execute(
            "INSERT INTO platform_roles (name, access) VALUES "
            "('Канцелярия и резолюция', '{\"eds.inbox\": \"full\"}'::jsonb), "
            "('Менеджер-универсал', '{\"crm.leads\": \"full\"}'::jsonb)"
        )

    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        rows: dict[str, dict[str, str]] = dict(
            conn.execute("SELECT coalesce(code, name), access FROM platform_roles").fetchall()
        )
        assert rows["tpl:REGISTRAR"]["eds.inbox"] == "read"
        assert rows["tpl:REGISTRAR"]["eds.inbox.register"] == "full"
        assert "tpl:MANAGER_ALL" not in rows  # имя занято ролью администратора — пропуск
        assert rows["Менеджер-универсал"] == {"crm.leads": "full"}
        assert rows["Канцелярия и резолюция"]["eds.inbox.register"] == "full"
        assert rows["DIRECTOR"]["eds.inbox.register"] == "full"
        conn.execute("DELETE FROM platform_roles WHERE code IS NULL")

    command.downgrade(alembic_config, before)
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        director = conn.execute(
            "SELECT access FROM platform_roles WHERE code = 'DIRECTOR'"
        ).fetchone()
        assert director is not None
        assert "eds.inbox.register" not in director[0]
        assert conn.execute(
            "SELECT count(*) FROM platform_roles WHERE code = 'tpl:REGISTRAR'"
        ).fetchone() == (0,)

    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        codes = {r[0] for r in conn.execute("SELECT code FROM platform_roles").fetchall()}
        assert {"tpl:REGISTRAR", "tpl:MANAGER_ALL"} <= codes


def test_registrar_template_triages_leads_and_downgrade_returns_full(
    alembic_config: Config, live_settings: Settings
) -> None:
    """D17G-1: «Делопроизводитель» из шаблона — `crm.leads: read` + `crm.leads.triage: full`,
    признак базовой роли — `viewer`; «Менеджер-универсал» и роль, которую администратор уже
    поменял, не трогаются; у передачи есть «кто передал» и «тип обращения»; downgrade — обратно."""
    before = "bf63b9342895"
    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        # TRUNCATE users каскадом чистит и роли; шаблоны пилота вернёт миграция P8.
        conn.execute("TRUNCATE users, audit_log, procrastinate_jobs RESTART IDENTITY CASCADE")
    command.downgrade(alembic_config, "ac71231f330f")
    command.upgrade(alembic_config, before)

    def role(conn: psycopg.Connection, code: str) -> tuple[dict[str, str], int]:
        row = conn.execute(
            "SELECT access, version FROM platform_roles WHERE code = %s", (code,)
        ).fetchone()
        assert row is not None
        return dict(row[0]), int(row[1])

    def base_role(conn: psycopg.Connection, user_id: int) -> list[str]:
        rows = conn.execute(
            "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
            "WHERE ur.user_id = %s ORDER BY r.name",
            (user_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def give(conn: psycopg.Connection, user_id: int, code: str) -> None:
        conn.execute(
            "INSERT INTO user_platform_roles (user_id, role_id) "
            "SELECT %s, id FROM platform_roles WHERE code = %s",
            (user_id, code),
        )

    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        clerk = _seed_user(conn, "clerk@x.uz", "manager")
        give(conn, clerk, "tpl:REGISTRAR")
        seller = _seed_user(conn, "seller@x.uz", "manager")
        give(conn, seller, "tpl:MANAGER_ALL")
        registrar, version = role(conn, "tpl:REGISTRAR")
        assert registrar["crm.leads"] == "full"
        manager_all = role(conn, "tpl:MANAGER_ALL")

    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        after, after_version = role(conn, "tpl:REGISTRAR")
        assert after == {**registrar, "crm.leads": "read", "crm.leads.triage": "full"}
        assert after_version == version + 1
        assert role(conn, "tpl:MANAGER_ALL") == manager_all
        assert base_role(conn, clerk) == ["viewer"]
        assert base_role(conn, seller) == ["manager"]
        columns = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'escalations'"
            ).fetchall()
        }
        assert {"handed_by_user_id", "request_type"} <= columns

    command.upgrade(alembic_config, "head")  # повтор — без изменений
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        assert role(conn, "tpl:REGISTRAR") == (after, after_version)

    command.downgrade(alembic_config, before)
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        back, back_version = role(conn, "tpl:REGISTRAR")
        assert back == registrar
        assert back_version == after_version + 1
        assert base_role(conn, clerk) == ["manager"]

    # Роль, которую администратор уже перевёл на чтение лидов, миграция не трогает.
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        conn.execute(
            'UPDATE platform_roles SET access = access || \'{"crm.leads": "read"}\'::jsonb '
            "WHERE code = 'tpl:REGISTRAR'"
        )
    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        edited, _ = role(conn, "tpl:REGISTRAR")
        assert edited["crm.leads"] == "read"
        assert "crm.leads.triage" not in edited


def test_admin_signing_manage_and_downgrade_removes(
    alembic_config: Config, live_settings: Settings
) -> None:
    """44c4ccb1a36d (SIGN-2, ADR-0024 п. 1): у «Администратора» `eds.signing.manage` — `full`,
    версия растёт."""

    def admin() -> tuple[str | None, int]:
        with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
            row = conn.execute(
                "SELECT access->>'eds.signing.manage', version FROM platform_roles "
                "WHERE code = 'ADMIN'"
            ).fetchone()
        assert row is not None
        return row[0], int(row[1])

    with psycopg.connect(live_settings.libpq_dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO platform_roles (code, name, is_system, access) VALUES "
            "('ADMIN', 'Администратор', true, '{\"admin\": \"full\"}'::jsonb) "
            "ON CONFLICT (code) DO NOTHING"
        )

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "5d5089811bac")
    level, version = admin()
    assert level is None

    command.upgrade(alembic_config, "44c4ccb1a36d")
    assert admin() == ("full", version + 1)

    command.upgrade(alembic_config, "head")  # повтор — без изменений
    assert admin()[0] == "full"
