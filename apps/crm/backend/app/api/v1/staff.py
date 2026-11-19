"""Справочные данные о коллегах для любого сотрудника: фото (W15-H6) и справочник (план СУЩ-3)."""

from typing import Annotated

from fastapi import APIRouter, Path, Response
from pydantic import BaseModel

from app.api.deps import ContainerDep
from app.api.v1.me import Settled
from app.domain.errors import NotFoundError

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])


class StaffCard(BaseModel):
    """Сотрудник для ссылки «кто сделал» (СУЩ-3): то, что видит любой коллега.

    Без почты, телефона и ролей.
    """

    id: int
    full_name: str
    position: str | None
    #: Версия фото (секунды epoch замены); `None` — фото нет, рисуются инициалы
    avatar_version: int | None
    is_active: bool


@router.get("", response_model=list[StaffCard])
async def list_staff(_: Settled, container: ContainerDep) -> list[StaffCard]:
    """Все сотрудники, включая отключённых: старый документ по-прежнему называет человека."""
    return [
        StaffCard(
            id=view.id,
            full_name=view.full_name,
            position=view.position,
            avatar_version=view.avatar_version,
            is_active=view.is_active,
        )
        for view in await container.user_service.list_all()
    ]


@router.get(
    "/{user_id}/avatar",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}}},
)
async def get_avatar(
    user_id: Annotated[int, Path(gt=0)], _: Settled, container: ContainerDep
) -> Response:
    """Фото коллеги как есть; нет фото или сотрудник отключён — 404 (рисуются инициалы)."""
    file = await container.staff_profile.read_avatar(user_id)
    if file is None:
        raise NotFoundError("avatar not found")
    return Response(
        content=file.data,
        media_type=file.content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{file.version}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
