"""Пользователи (admin): создание с временным паролем, роли, деактивация, сброс пароля."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import ContainerDep, require
from app.schemas.auth import PasswordReset, UserCreate, UserCreated, UserOut, UserUpdate
from app.security.principal import Principal
from app.services.users import UserPatch, UserView

router = APIRouter(prefix="/api/v1/users", tags=["users"])

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
    )


@router.get("", response_model=list[UserOut])
async def list_users(_: Reader, container: ContainerDep) -> list[UserOut]:
    return [to_out(v) for v in await container.user_service.list_all()]


@router.post("", response_model=UserCreated, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, who: Writer, container: ContainerDep) -> UserCreated:
    view, password = await container.user_service.create(
        who.actor, body.email, body.full_name, body.roles
    )
    return UserCreated(user=to_out(view), temporary_password=password)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, _: Reader, container: ContainerDep) -> UserOut:
    return to_out(await container.user_service.get(user_id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int, body: UserUpdate, who: Writer, container: ContainerDep
) -> UserOut:
    patch = UserPatch(
        full_name=body.full_name,
        roles=list(body.roles) if body.roles is not None else None,
        is_active=body.is_active,
        tg_user_id=body.tg_user_id,
        clear_tg_user_id=body.clear_tg_user_id,
        transfer_to_user_id=body.transfer_to_user_id,
    )
    return to_out(await container.user_service.update(who.actor, user_id, patch))


@router.post("/{user_id}/reset-password", response_model=PasswordReset)
async def reset_password(user_id: int, who: Writer, container: ContainerDep) -> PasswordReset:
    password = await container.user_service.reset_password(who.actor, user_id)
    return PasswordReset(temporary_password=password)
