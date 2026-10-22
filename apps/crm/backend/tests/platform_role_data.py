"""Роли Платформы для тестов: строки системных ролей и шаблонов каталога без базы."""

from typing import Any

from app.domain.platform_roles import RoleGrant, default_roles, role_code_for
from app.models.platform_roles import PlatformRole

# Старые коды ролей в порядке прежнего контракта; id — условные, по порядку.
LEGACY = ("MANAGER", "DIRECTOR", "SUPPLY", "ENGINEER", "ACCOUNTANT", "ADMIN")


def make_role(legacy: str, role_id: int | None = None) -> PlatformRole:
    """Роль каталога (`MANAGER` -> `tpl:MANAGER`, `ADMIN` -> системная) как объект модели."""
    row: dict[str, Any] = next(r for r in default_roles() if r["code"] == role_code_for(legacy))
    return PlatformRole(
        id=role_id if role_id is not None else LEGACY.index(legacy) + 1,
        code=row["code"],
        name=row["name"],
        description="",
        is_system=row["is_system"],
        access=dict(row["access"]),
        restricted_fields=list(row["restricted_fields"]),
    )


def make_grant(legacy: str) -> RoleGrant:
    """То же, что `make_role`, но как вход вычисления прав (без модели БД)."""
    role = make_role(legacy)
    return RoleGrant(dict(role.access), tuple(role.restricted_fields), role.code)
