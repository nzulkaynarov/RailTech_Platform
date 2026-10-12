"""Профиль текущего пользователя и матрица прав для фронта (SPEC §10.3)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ContainerDep, PrincipalDep, get_rbac
from app.api.v1.users import to_out
from app.schemas.auth import MePatch, PermissionsResponse, UserOut
from app.schemas.leads import ActionResult
from app.security.rbac import Rbac
from app.services.staff_notifier import StaffNotifier

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("", response_model=UserOut)
async def me(principal: PrincipalDep, container: ContainerDep) -> UserOut:
    return to_out(await container.user_service.get(principal.user_id))


@router.patch("", response_model=UserOut)
async def update_me(body: MePatch, principal: PrincipalDep, container: ContainerDep) -> UserOut:
    svc = container.user_service
    view = await svc.get(principal.user_id)
    if body.ui_mode is not None:
        view = await svc.set_ui_mode(principal.actor, principal.user_id, body.ui_mode)
    if body.notify_system is not None or body.notify_leads is not None:
        view = await svc.set_notify(
            principal.actor,
            principal.user_id,
            system=body.notify_system,
            leads=body.notify_leads,
        )
    return to_out(view)


@router.post("/test-notification", response_model=ActionResult)
async def test_notification(principal: PrincipalDep, container: ContainerDep) -> ActionResult:
    """«Проверить доставку»: личное сообщение от бота себе; отказ Telegram → 409 с его текстом."""
    notifier = StaffNotifier(container.session_factory, container.telegram_bot)
    await notifier.test_message(principal.user_id)
    return ActionResult()


@router.get("/permissions", response_model=PermissionsResponse)
async def permissions(
    principal: PrincipalDep, rbac: Annotated[Rbac, Depends(get_rbac)]
) -> PermissionsResponse:
    """Только для скрытия UI; истина — проверки на каждом эндпоинте."""
    matrix = rbac.permissions(principal.roles)
    if principal.must_change_password:
        matrix = {r: dict.fromkeys(actions, False) for r, actions in matrix.items()}
    return PermissionsResponse(roles=list(principal.roles), permissions=matrix)
