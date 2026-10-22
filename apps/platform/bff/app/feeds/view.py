"""Роли «вида» для агрегатов: явный `role`, иначе активная роль, иначе все роли (Q-PLT-12-1)."""

from app.deps import Authed
from app.errors import PlatformError
from app.rbac import view_roles
from app.rbac_generated import RoleCode


def roles_of_view(authed: Authed, role: RoleCode | None) -> list[RoleCode]:
    if role is not None:
        if role not in authed.roles:
            raise PlatformError(
                "FORBIDDEN",
                "Эта роль вам не назначена.",
                status_code=403,
                details={"reason": "role_not_assigned", "role": role},
            )
        return [role]
    return view_roles(authed.data.platform_roles, authed.data.active_role)
