"""Матрица прав из seed-политик: роль × ресурс × действие."""

import pytest

from app.config import Settings
from app.domain.platform_roles import crm_policies, role_subject
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
    got = _rights(["viewer"], ["DIRECTOR"])

    assert ("users", "read") in got
    assert ("users", "write") not in got
    assert not PLATFORM.allowed(["viewer"], "users", "read")  # seed `viewer` не расширен
    for other in (["SUPPLY"], ["ENGINEER"], ["MANAGER"], ["ACCOUNTANT"], []):
        assert ("users", "read") not in _rights(["viewer"], other), other
    assert PLATFORM.permissions(["viewer"], [ROLE_IDS["DIRECTOR"]])["users"] == {
        "read": True,
        "write": False,
    }


def test_roles_of_a_user_are_united_and_unknown_role_ids_give_nothing() -> None:
    assert _rights(["viewer"], ["MANAGER", "DIRECTOR"]) >= _rights(["viewer"], ["MANAGER"])
    assert _rights(["viewer"], ["MANAGER", "DIRECTOR"]) >= _rights(["viewer"], ["DIRECTOR"])
    assert not PLATFORM.allowed(["viewer"], "users", "read", [999])
    assert PLATFORM.allowed(["viewer"], "leads", "read", [999])  # базовая роль действует


def test_accountant_reads_the_company_summary_spend_without_working_the_leads() -> None:
    got = _rights(["viewer"], ["ACCOUNTANT"])

    assert ("spend", "read") in got  # dashboard.summary read
    assert {("leads", "reply"), ("leads", "note")} <= got  # chats.external full
    assert ("leads", "take") not in got
    assert ("clients", "write") not in got
