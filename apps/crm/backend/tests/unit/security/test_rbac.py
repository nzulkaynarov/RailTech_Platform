"""Матрица прав из seed-политик: роль × ресурс × действие."""

import pytest

from app.config import Settings
from app.security.rbac import CATALOG, Rbac, read_seed

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


def test_director_platform_role_adds_only_users_read_on_top_of_viewer() -> None:
    """CRM-01c: seed `viewer` не расширен; право — по роли Платформы."""
    got = {
        (r, a)
        for r, actions in CATALOG.items()
        for a in actions
        if RBAC.allowed(["viewer"], r, a, ["DIRECTOR"])
    }

    assert got == VIEWER | {("users", "read")}
    assert not RBAC.allowed(["viewer"], "users", "read")
    for other in (["SUPPLY"], ["ENGINEER"], ["MANAGER"], ["ACCOUNTANT"], ["bogus"]):
        assert not RBAC.allowed(["viewer"], "users", "read", other)
    assert RBAC.permissions(["viewer"], ["DIRECTOR"])["users"] == {"read": True, "write": False}
