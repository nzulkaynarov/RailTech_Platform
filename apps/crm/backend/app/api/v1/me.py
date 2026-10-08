"""Профиль текущего пользователя и матрица прав для фронта (SPEC §10.3)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ContainerDep, PrincipalDep, get_rbac
from app.api.v1.users import to_out
from app.schemas.auth import MePatch, PermissionsResponse, UserOut
from app.security.rbac import Rbac

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("", response_model=UserOut)
async def me(principal: PrincipalDep, container: ContainerDep) -> UserOut:
    return to_out(await container.user_service.get(principal.user_id))


@router.patch("", response_model=UserOut)
async def update_me(body: MePatch, principal: PrincipalDep, container: ContainerDep) -> UserOut:
    view = await container.user_service.set_ui_mode(
        principal.actor, principal.user_id, body.ui_mode
    )
    return to_out(view)


@router.get("/permissions", response_model=PermissionsResponse)
async def permissions(
    principal: PrincipalDep, rbac: Annotated[Rbac, Depends(get_rbac)]
) -> PermissionsResponse:
    """Только для скрытия UI; истина — проверки на каждом эндпоинте."""
    matrix = rbac.permissions(principal.roles)
    if principal.must_change_password:
        matrix = {r: dict.fromkeys(actions, False) for r, actions in matrix.items()}
    return PermissionsResponse(roles=list(principal.roles), permissions=matrix)
