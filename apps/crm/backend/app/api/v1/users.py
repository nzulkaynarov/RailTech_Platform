"""Пользователи (admin): создание с временным паролем, роли, деактивация, сброс пароля."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status

from app.api.deps import ContainerDep, require
from app.api.v1.integrations import queued_out
from app.schemas.auth import (
    PasswordReset,
    PlatformRoleRef,
    SecondFactorResetRequest,
    UserCreate,
    UserCreated,
    UserOut,
    UserUpdate,
)
from app.schemas.integrations import EmailQueuedOut
from app.security.principal import Principal
from app.services.user_views import UserPatch, UserView

router = APIRouter(prefix="/api/v1/users", tags=["users"])

StepUpHeader = Annotated[
    str | None, Header()
]  # `X-Step-Up-Token`: свежий код второго фактора (ДВ-4б)

Reader = Annotated[Principal, Depends(require("users", "read"))]
Writer = Annotated[Principal, Depends(require("users", "write"))]


def to_out(view: UserView) -> UserOut:
    return UserOut(
        id=view.id,
        email=view.email,
        full_name=view.full_name,
        roles=view.roles,
        is_active=view.is_active,
        tg_user_id=view.tg_user_id,
        must_change_password=view.must_change_password,
        ui_mode=view.ui_mode,
        notify_system=view.notify_system,
        notify_leads=view.notify_leads,
        notify_decisions=view.notify_decisions,
        notify_tasks=view.notify_tasks,
        tg_dm_failed_at=view.tg_dm_failed_at,
        platform_access=view.platform_access,
        erp_role_codes=view.erp_role_codes,
        platform_role_ids=view.platform_role_ids,
        platform_role_refs=[
            PlatformRoleRef(
                id=r.id,
                name=r.name,
                system=r.system,
                code=r.code,
            )
            for r in view.platform_role_refs
        ],
        position=view.position,
        is_service=view.is_service,
        language=view.language,
        erp_sync=view.erp_sync,
        erp_sync_error=view.erp_sync_error,
        phone=view.phone,
        timezone=view.timezone,
        email_signature=view.email_signature,
        show_test=view.show_test,
        tg_username=view.tg_username,
        avatar_version=view.avatar_version,
        deputy_user_id=view.deputy_user_id,
        deputy_from=view.deputy_from,
        deputy_to=view.deputy_to,
        onboarding_done=view.onboarding_done,
    )


@router.get("", response_model=list[UserOut])
async def list_users(_: Reader, container: ContainerDep) -> list[UserOut]:
    return [to_out(v) for v in await container.user_service.list_all()]


@router.post("", response_model=UserCreated, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    who: Writer,
    container: ContainerDep,
    x_step_up_token: StepUpHeader = None,
) -> UserCreated:
    """Новый сотрудник. Роль при создании — выдача роли: нужен свежий код (`X-Step-Up-Token`)."""
    if body.platform_role_ids or body.roles:
        await container.second_factor_service.require_step_up(who.user_id, x_step_up_token)
    view, password = await container.user_service.create(
        who.actor,
        body.email,
        body.full_name,
        body.roles or [],
        platform_role_ids=body.platform_role_ids,
        position=body.position,
    )
    return UserCreated(user=to_out(view), temporary_password=password)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, _: Reader, container: ContainerDep) -> UserOut:
    return to_out(await container.user_service.get(user_id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    who: Writer,
    container: ContainerDep,
    x_step_up_token: StepUpHeader = None,
) -> UserOut:
    """Изменить пользователя. Роли Платформы — полный набор `platform_role_ids`; пустой набор —
    422 `roles_required` (R3-D-1: закрыть доступ — `is_active = false`); снять последнего
    администратора или директора — 409 `last_admin` / `last_director`. Выдача роли (появилась роль,
    которой не было) требует свежий код второго фактора в `X-Step-Up-Token` (ДВ-4б), иначе 403
    `step_up_required`."""
    patch = UserPatch(
        full_name=body.full_name,
        roles=list(body.roles) if body.roles is not None else None,
        is_active=body.is_active,
        tg_user_id=body.tg_user_id,
        clear_tg_user_id=body.clear_tg_user_id,
        transfer_to_user_id=body.transfer_to_user_id,
        platform_access=body.platform_access,
        erp_role_codes=body.erp_role_codes,
        platform_role_ids=body.platform_role_ids,
        position=body.position,
        language=body.language,
        is_service=body.is_service,
    )
    if await container.user_service.adds_roles(user_id, patch):
        await container.second_factor_service.require_step_up(who.user_id, x_step_up_token)
    # Замещение — те же правила и журнал (`user.deputy_set` / `user.deputy_cleared`), что у профиля,
    # но от имени администратора: сотрудник болен или не вошёл, а его задачи стоят.
    if body.clear_deputy:
        await container.staff_deputy.clear(who.actor, user_id)
    elif body.deputy_user_id is not None and body.deputy_from and body.deputy_to:
        await container.staff_deputy.set(
            who.actor, user_id, body.deputy_user_id, body.deputy_from, body.deputy_to
        )
    if patch == UserPatch():
        return to_out(await container.user_service.get(user_id))
    return to_out(await container.user_service.update(who.actor, user_id, patch))


@router.post("/{user_id}/erp-sync", response_model=UserOut)
async def erp_sync(user_id: int, who: Writer, container: ContainerDep) -> UserOut:
    """Повторить синхронизацию доступа с ERP (СЦ-8): активному с доступом — выдача, иначе отзыв
    сессий. Задача идёт в очередь; итог — в `erp_sync` (`pending` → `ok` | `error`)."""
    return to_out(await container.user_service.erp_resync(who.actor, user_id))


@router.post("/{user_id}/reset-password", response_model=PasswordReset)
async def reset_password(user_id: int, who: Writer, container: ContainerDep) -> PasswordReset:
    password = await container.user_service.reset_password(who.actor, user_id)
    return PasswordReset(temporary_password=password)


@router.post("/{user_id}/invite", response_model=EmailQueuedOut)
async def invite_user(user_id: int, who: Writer, container: ContainerDep) -> EmailQueuedOut:
    """Пригласить по почте (ДВ-7): письмо с одноразовой ссылкой «Задайте пароль» (72 ч), без пароля.

    Прежний пароль и сессии закрываются, статус — «Приглашён». Без коннектора — 409
    `smtp_not_configured`, ничего не меняется (выдайте временный пароль на экране); без
    `SECRETS_KEY` — 409 `secrets_key_missing`; больше 3 ссылок в час на сотрудника — 429.
    Итог доставки — в журнале писем.
    """
    return queued_out(await container.user_invites.invite(who.actor, user_id))


@router.post("/{user_id}/reset-password/email", response_model=EmailQueuedOut)
async def reset_password_by_email(
    user_id: int, who: Writer, container: ContainerDep
) -> EmailQueuedOut:
    """Сбросить пароль по почте (ДВ-7): письмо с одноразовой ссылкой на 1 час, пароля в письме нет.

    Прежний пароль закрывается, сессии завершаются. Без коннектора — 409 `smtp_not_configured`,
    пароль не меняется; больше 3 ссылок в час на сотрудника — 429.
    """
    return queued_out(await container.user_invites.reset_password_email(who.actor, user_id))


@router.post("/{user_id}/second-factor/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_second_factor(
    user_id: int, body: SecondFactorResetRequest, who: Writer, container: ContainerDep
) -> Response:
    """Сбросить второй фактор сотруднику (потерян телефон; ДВ-4б): причина — в журнал, его сессии
    закрываются, при следующем входе он настраивает фактор заново. Себе — 409
    `second_factor_self_reset`; фактор не включён — 422 `second_factor_not_enabled`."""
    await container.second_factor_service.reset(who.actor, user_id, body.reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
