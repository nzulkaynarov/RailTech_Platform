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
    ("stream", "read"),
    ("dashboard", "read"),
    ("clients", "read"),
    ("clients", "write"),
    ("documents", "read"),
    ("documents", "write"),
    ("deals", "read"),
    ("deals", "write"),
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
    }
