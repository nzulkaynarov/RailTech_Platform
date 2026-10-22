"""Профиль текущего пользователя и матрица прав для фронта (SPEC §10.3)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ContainerDep, PrincipalDep, get_rbac
from app.api.v1.users import to_out
from app.container import Container
from app.schemas.auth import MeOut, MePatch, PermissionsResponse
from app.schemas.leads import ActionResult
from app.security.rbac import Rbac
from app.services.staff_notifier import StaffNotifier
from app.services.users import UserView

router = APIRouter(prefix="/api/v1/me", tags=["me"])


def _me_out(view: UserView, container: Container) -> MeOut:
    return MeOut(
        **to_out(view).model_dump(),
        sso_enabled=container.settings.platform_sso_enabled,
    )


@router.get("", response_model=MeOut)
async def me(principal: PrincipalDep, container: ContainerDep) -> MeOut:
    return _me_out(await container.user_service.get(principal.user_id), container)


@router.patch("", response_model=MeOut)
async def update_me(body: MePatch, principal: PrincipalDep, container: ContainerDep) -> MeOut:
    svc = container.user_service
    view = await svc.get(principal.user_id)
    if body.ui_mode is not None:
        view = await svc.set_ui_mode(principal.actor, principal.user_id, body.ui_mode)
    if body.language is not None:
        view = await svc.set_language(principal.actor, principal.user_id, body.language)
    if body.notify_system is not None or body.notify_leads is not None:
        view = await svc.set_notify(
            principal.actor,
            principal.user_id,
            system=body.notify_system,
            leads=body.notify_leads,
        )
    return _me_out(view, container)


@router.post("/test-notification", response_model=ActionResult)
async def test_notification(principal: PrincipalDep, container: ContainerDep) -> ActionResult:
    """«Проверить доставку»: личное сообщение от бота себе; отказ Telegram → 409 с его текстом."""
    notifier = StaffNotifier(container.session_factory, await container.telegram_bot())
    await notifier.test_message(principal.user_id)
    return ActionResult()


@router.get("/permissions", response_model=PermissionsResponse)
async def permissions(
    principal: PrincipalDep, rbac: Annotated[Rbac, Depends(get_rbac)]
) -> PermissionsResponse:
    """Только для скрытия UI; истина — проверки на каждом эндпоинте."""
    matrix = rbac.permissions(principal.roles, principal.platform_roles)
    if principal.must_change_password:
        matrix = {r: dict.fromkeys(actions, False) for r, actions in matrix.items()}
    return PermissionsResponse(roles=list(principal.roles), permissions=matrix)
