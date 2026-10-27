"""Профиль текущего пользователя и матрица прав для фронта (SPEC §10.3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import ContainerDep, PrincipalDep, get_rbac
from app.api.v1.users import to_out
from app.container import Container
from app.domain.errors import PasswordChangeRequiredError
from app.domain.staff_profile import AVATAR_MAX_BYTES
from app.schemas.auth import (
    CoveredOut,
    DeputyCandidate,
    DeputyIn,
    MeOut,
    MePatch,
    PermissionsResponse,
    PlatformRoleGrantRef,
    TelegramLinkOut,
)
from app.schemas.leads import ActionResult
from app.security.principal import Principal
from app.security.rbac import Rbac
from app.services.staff_notifier import StaffNotifier
from app.services.user_views import UserView

router = APIRouter(prefix="/api/v1/me", tags=["me"])


async def _settled(principal: PrincipalDep) -> Principal:
    """Профильные действия — после смены временного пароля."""
    if principal.must_change_password:
        raise PasswordChangeRequiredError("change the temporary password first")
    return principal


Settled = Annotated[Principal, Depends(_settled)]


async def _me_out(view: UserView, container: Container) -> MeOut:
    base = to_out(view).model_dump(exclude={"platform_role_refs"})
    refs = [
        PlatformRoleGrantRef(
            id=r.id,
            name=r.name,
            system=r.system,
            code=r.code,
            access=dict(r.access),
            restricted_fields=list(r.restricted_fields),
        )
        for r in view.platform_role_refs
    ]
    return MeOut(
        **base,
        platform_role_refs=refs,
        sso_enabled=container.settings.platform_sso_enabled,
        deputy_name=await container.staff_deputy.deputy_name(view.deputy_user_id),
    )


@router.get("", response_model=MeOut)
async def me(principal: PrincipalDep, container: ContainerDep) -> MeOut:
    return await _me_out(await container.user_service.get(principal.user_id), container)


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
    profile = {
        k: getattr(body, k)
        for k in ("full_name", "phone", "timezone", "email_signature")
        if getattr(body, k) is not None
    }
    if profile:
        # Только свой профиль: `user_id` — из токена, должность и роли в тело не принимаются.
        view = await container.staff_profile.update(principal.actor, principal.user_id, **profile)
    return await _me_out(view, container)


@router.put("/avatar", response_model=MeOut)
async def put_avatar(
    principal: Settled, container: ContainerDep, avatar: Annotated[UploadFile, File()]
) -> MeOut:
    """Фото профиля (клиент уже обрезал по кругу): PNG/JPEG/WebP до 1 МБ, тип — по содержимому."""
    data = await avatar.read(AVATAR_MAX_BYTES + 1)
    view = await container.staff_profile.set_avatar(
        principal.actor, principal.user_id, data, avatar.content_type
    )
    return await _me_out(view, container)


@router.delete("/avatar", response_model=MeOut)
async def delete_avatar(principal: Settled, container: ContainerDep) -> MeOut:
    view = await container.staff_profile.remove_avatar(principal.actor, principal.user_id)
    return await _me_out(view, container)


@router.post("/telegram-link", response_model=TelegramLinkOut)
async def telegram_link(principal: Settled, container: ContainerDep) -> TelegramLinkOut:
    """Ссылка `t.me/<бот>?start=staff_<код>` на 10 минут; прежняя ссылка перестаёт работать."""
    ticket = await container.staff_telegram_link.begin(principal.user_id)
    return TelegramLinkOut(url=ticket.url, expires_at=ticket.expires_at)


@router.delete("/telegram-link", response_model=MeOut)
async def telegram_unlink(principal: Settled, container: ContainerDep) -> MeOut:
    await container.staff_telegram_link.unlink(principal.actor, principal.user_id)
    return await _me_out(await container.user_service.get(principal.user_id), container)


@router.get("/deputy-candidates", response_model=list[DeputyCandidate])
async def deputy_candidates(principal: Settled, container: ContainerDep) -> list[DeputyCandidate]:
    items = await container.staff_deputy.candidates(principal.user_id)
    return [DeputyCandidate(id=c.id, full_name=c.full_name, position=c.position) for c in items]


@router.put("/deputy", response_model=MeOut)
async def put_deputy(body: DeputyIn, principal: Settled, container: ContainerDep) -> MeOut:
    await container.staff_deputy.set(
        principal.actor, principal.user_id, body.deputy_user_id, body.date_from, body.date_to
    )
    return await _me_out(await container.user_service.get(principal.user_id), container)


@router.delete("/deputy", response_model=MeOut)
async def delete_deputy(principal: Settled, container: ContainerDep) -> MeOut:
    await container.staff_deputy.clear(principal.actor, principal.user_id)
    return await _me_out(await container.user_service.get(principal.user_id), container)


@router.get("/covering", response_model=list[CoveredOut])
async def covering(principal: Settled, container: ContainerDep) -> list[CoveredOut]:
    """За кого этот сотрудник сегодня заместитель: BFF добавляет их очередь в «Мою очередь»."""
    items = await container.staff_deputy.covering(principal.user_id)
    return [
        CoveredOut(
            user_id=c.user_id, full_name=c.full_name, date_from=c.date_from, date_to=c.date_to
        )
        for c in items
    ]


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
    matrix = rbac.permissions(principal.rbac_roles, principal.platform_role_ids)
    if principal.must_change_password:
        matrix = {r: dict.fromkeys(actions, False) for r, actions in matrix.items()}
    return PermissionsResponse(roles=list(principal.roles), permissions=matrix)
