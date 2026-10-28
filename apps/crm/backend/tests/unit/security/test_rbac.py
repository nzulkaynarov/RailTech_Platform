"""Матрица прав из seed-политик: роль × ресурс × действие."""

import pytest

from app.config import Settings
from app.domain.platform_roles import crm_policies, role_subject
from app.security.principal import Principal
from app.security.rbac import CATALOG, Rbac, read_seed
from tests.platform_role_data import make_role

CASBIN_DIR = Settings(_env_file=None).casbin_dir
RBAC = Rbac.from_rules(CASBIN_DIR, read_seed(CASBIN_DIR / "policy.seed.csv"))

MANAGER = {
    ("leads", "read"),
    ("leads", "take"),
    ("leads", "work"),
    ("leads", "reply"),
    ("leads", "note"),
    ("leads", "assist"),
    ("leads", "create"),  # «Новый лид» вручную (M3-CRM-05)
    ("stream", "read"),
    ("dashboard", "read"),
    ("clients", "read"),
    ("clients", "write"),
    ("documents", "read"),
    ("documents", "write"),
    ("deals", "read"),
    ("deals", "write"),
    ("kb", "read"),  # база знаний — только просмотр (аудит 2026-10-12)
    ("reply_templates", "read"),  # шаблоны ответов правит админ
}
VIEWER = {
    ("leads", "read"),
    ("stream", "read"),
    ("dashboard", "read"),
    ("clients", "read"),
    ("deals", "read"),
}
ALL = {(r, a) for r, actions in CATALOG.items() for a in actions}


@pytest.mark.parametrize(
    ("role", "allowed"),
    [("admin", ALL), ("manager", MANAGER), ("viewer", VIEWER), ("ghost", set())],
)
def test_matrix(role: str, allowed: set[tuple[str, str]]) -> None:
    for resource, action in sorted(ALL):
        assert RBAC.allowed([role], resource, action) is ((resource, action) in allowed), (
            role,
            resource,
            action,
        )


def test_union_of_roles() -> None:
    assert RBAC.allowed(["viewer", "manager"], "leads", "take")
    assert not RBAC.allowed([], "leads", "read")


def test_permissions_payload_shape() -> None:
    perms = RBAC.permissions(["viewer"])
    assert set(perms) == set(CATALOG)
    assert perms["leads"] == {
        "read": True,
        "take": False,
        "work": False,
        "reply": False,
        "note": False,
        "assist": False,
        "create": False,
    }


# Роли Платформы: правила `pr:<id>` пишутся по матрице роли (id условные, как в миграции).
ROLE_IDS = {"ADMIN": 1, "DIRECTOR": 2, "MANAGER": 3, "SUPPLY": 4, "ENGINEER": 5, "ACCOUNTANT": 6}


def _with_platform_roles() -> Rbac:
    rules = read_seed(CASBIN_DIR / "policy.seed.csv")
    for legacy, role_id in ROLE_IDS.items():
        for resource, action in sorted(crm_policies(make_role(legacy, role_id).access)):
            rules.append([role_subject(role_id), "crm", resource, action])
    return Rbac.from_rules(CASBIN_DIR, rules)


PLATFORM = _with_platform_roles()


def _rights(roles: list[str], platform: list[str]) -> set[tuple[str, str]]:
    ids = [ROLE_IDS[code] for code in platform]
    return {
        (r, a)
        for r, actions in CATALOG.items()
        for a in actions
        if PLATFORM.allowed(roles, r, a, ids)
    }


def test_director_reads_users_on_top_of_viewer_by_the_computed_admin_read() -> None:
    """`users:read` директору даёт вычисленный раздел `admin` (read), а не код роли."""
    got = _rights([], ["DIRECTOR"])

    assert ("users", "read") in got
    assert ("users", "write") not in got
    assert not PLATFORM.allowed(["viewer"], "users", "read")  # seed `viewer` не расширен
    for other in (["SUPPLY"], ["ENGINEER"], ["MANAGER"], ["ACCOUNTANT"], []):
        assert ("users", "read") not in _rights([], other), other
    assert PLATFORM.permissions(["viewer"], [ROLE_IDS["DIRECTOR"]])["users"] == {
        "read": True,
        "write": False,
    }


def test_roles_of_a_user_are_united_and_unknown_role_ids_give_nothing() -> None:
    assert _rights([], ["MANAGER", "DIRECTOR"]) >= _rights([], ["MANAGER"])
    assert _rights([], ["MANAGER", "DIRECTOR"]) >= _rights([], ["DIRECTOR"])
    assert not PLATFORM.allowed(["viewer"], "users", "read", [999])
    assert PLATFORM.allowed(["viewer"], "leads", "read", [999])  # базовая роль действует


def test_accountant_reads_the_company_summary_spend_without_working_the_leads() -> None:
    got = _rights([], ["ACCOUNTANT"])

    assert ("spend", "read") in got  # dashboard.summary read
    assert {("leads", "reply"), ("leads", "note")} <= got  # chats.external full
    assert ("leads", "take") not in got
    assert ("clients", "write") not in got


def _custom(access: dict[str, str], role_id: int) -> Rbac:
    """Seed ролей CRM + правила одной роли Платформы."""
    rules = read_seed(CASBIN_DIR / "policy.seed.csv")
    rules += [[role_subject(role_id), "crm", r, a] for r, a in sorted(crm_policies(access))]
    return Rbac.from_rules(CASBIN_DIR, rules)


def _all(rbac: Rbac, principal: Principal) -> set[tuple[str, str]]:
    return {
        (r, a)
        for r, actions in CATALOG.items()
        for a in actions
        if rbac.allowed(principal.rbac_roles, r, a, principal.platform_role_ids)
    }


def _principal(roles: tuple[str, ...], ids: tuple[int, ...]) -> Principal:
    return Principal(1, "Тест", roles, platform_role_ids=ids)


def test_a_role_gives_exactly_its_own_rights_and_not_the_base_role_bundle() -> None:
    """Роль {crm.leads: full} не даёт clients:write (его даёт seed manager), а {chats.internal:
    full} — даже leads:read (его даёт seed viewer): базовая роль прав не даёт."""
    leads = _custom({"crm.leads": "full"}, 90)
    got = _all(leads, _principal(("manager",), (90,)))
    assert got == {(r, a) for r, a in crm_policies({"crm.leads": "full"})}
    assert ("clients", "write") not in got

    chat = _custom({"chats.internal": "full"}, 91)
    assert _all(chat, _principal(("viewer",), (91,))) == set()
    assert not chat.allowed(_principal(("viewer",), (91,)).rbac_roles, "leads", "read", (91,))
    assert chat.permissions((), (91,))["leads"]["read"] is False


# Бизнес-данные CRM: лиды, переписка, клиенты, сделки, документы клиентов, сводка (R3-D-2).
BUSINESS = {
    (r, a)
    for r in ("leads", "stream", "clients", "deals", "documents", "dashboard")
    for a in CATALOG[r]
}
# Администрирование CRM: сотрудники и роли, подключения, модели ИИ, настройки, журнал, копии.
ADMINISTRATION = {
    ("users", "read"),
    ("users", "write"),
    ("settings", "read"),
    ("settings", "write"),
    ("integrations", "read"),
    ("integrations", "write"),
    ("external_services", "read"),
    ("external_services", "write"),
    ("tickets", "read"),
    ("tickets", "write"),
    ("models", "read"),
    ("models", "test"),
    ("models", "write"),
    ("system", "read"),
    ("backups", "read"),
    ("backups", "write"),
    ("audit", "read"),
}


def test_the_system_admin_gets_the_catalog_admin_section_not_the_crm_admin_wildcard() -> None:
    """R3-D-2: системная «Администратор» — права раздела `admin` каталога, а не `admin` CRM
    (`*:*`): лиды, клиенты, сделки ей не положены, администрирование — да."""
    admin = _principal(("admin",), (ROLE_IDS["ADMIN"],))  # базовая роль CRM у неё — `admin`
    got = _all(PLATFORM, admin)

    assert admin.rbac_roles == ()
    assert admin.is_admin is False  # объектных исключений админа (чужой лид, сделка) нет
    assert got == set(crm_policies(make_role("ADMIN", ROLE_IDS["ADMIN"]).access))
    assert got >= ADMINISTRATION
    assert got.isdisjoint(BUSINESS), sorted(got & BUSINESS)
    assert PLATFORM.permissions(admin.rbac_roles, admin.platform_role_ids)[
        "leads"
    ] == dict.fromkeys(CATALOG["leads"], False)


def test_admin_and_director_get_the_director_rights_without_working_the_leads() -> None:
    """Администратор + Директор = объединение двух матриц: директорское чтение лидов и клиенты,
    но не `leads:take/reply/...`, которые раньше давал `admin` CRM."""
    both = _all(PLATFORM, _principal(("admin",), (ROLE_IDS["ADMIN"], ROLE_IDS["DIRECTOR"])))

    assert both == _rights([], ["ADMIN"]) | _rights([], ["DIRECTOR"])
    assert {("leads", "read"), ("clients", "write"), ("deals", "write")} <= both
    taken = {("leads", a) for a in ("take", "work", "reply", "note", "assist", "create")}
    assert both.isdisjoint(taken), sorted(both & taken)


def test_a_custom_admin_section_role_gives_the_same_as_the_system_admin() -> None:
    custom = _custom({"admin": "full"}, 92)
    got = _all(custom, _principal(("admin",), (92,)))  # роль с admin: full, но не системная
    assert ("users", "write") in got
    assert ("clients", "write") not in got
    assert got == set(crm_policies({"admin": "full"}))


def test_a_user_without_platform_roles_is_checked_by_the_crm_roles_as_before() -> None:
    manual = _principal(("manager",), ())
    assert manual.rbac_roles == ("manager",)
    assert RBAC.allowed(manual.rbac_roles, "clients", "write", manual.platform_role_ids)
    assert _principal(("admin",), ()).is_admin is True
    assert _principal(("admin",), (92,)).is_admin is False
    assert _principal(("admin",), (1,)).rbac_roles == ()  # роли Платформы вытесняют базовые
