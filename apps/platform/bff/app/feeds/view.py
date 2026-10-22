"""«Вид» для агрегатов: явный `role` (id), иначе активная роль, иначе все роли (Q-PLT-12-1)."""

from app.deps import Authed
from app.errors import PlatformError
from app.rbac import View, view_roles


def roles_of_view(authed: Authed, role: str | None) -> View:
    if role is not None:
        chosen = [r for r in authed.roles if str(r.id) == role]
        if not chosen:
            raise PlatformError(
                "FORBIDDEN",
                "Эта роль вам не назначена.",
                status_code=403,
                details={"reason": "role_not_assigned", "role": role},
            )
        return View.of(chosen)
    return View.of(view_roles(authed.roles, authed.data.active_role))
