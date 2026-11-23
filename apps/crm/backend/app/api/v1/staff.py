"""Справочные данные о коллегах для любого сотрудника: фото (W15-H6) и справочник (план СУЩ-3)."""

from typing import Annotated

from fastapi import APIRouter, Path, Response
from pydantic import BaseModel

from app.api.deps import ContainerDep
from app.api.v1.me import Settled
from app.domain.errors import NotFoundError
from app.security import audit

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])


class StaffCard(BaseModel):
    """Сотрудник для ссылки «кто сделал» (СУЩ-3): то, что видит любой коллега.

    Без почты и телефона: их открывает `POST /staff/{id}/contacts` с записью в журнал. Роли — только
    названиями (для карточки «Людей»), без матрицы прав.
    """

    id: int
    full_name: str
    position: str | None
    #: Версия фото (секунды epoch замены); `None` — фото нет, рисуются инициалы
    avatar_version: int | None
    is_active: bool
    #: Названия ролей Платформы словами (карточка сотрудника в «Людях»)
    roles: list[str] = []


class StaffContacts(BaseModel):
    """Телефон и почта сотрудника: отдаются только вместе с записью журнала `contact.reveal`."""

    id: int
    phone: str | None
    email: str | None


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
            roles=[ref.name for ref in view.platform_role_refs],
        )
        for view in await container.user_service.list_all()
    ]


@router.post("/{user_id}/contacts", response_model=StaffContacts)
async def reveal_staff_contacts(
    user_id: Annotated[int, Path(gt=0)], who: Settled, container: ContainerDep
) -> StaffContacts:
    """Показ телефона и почты коллеги (решение 10.11): запись «кто, когда, чьи» и ответ — в одной
    транзакции, нет записи — нет и контактов. Отключённый сотрудник — 404. Выгрузки нет."""
    view = await container.user_service.get(user_id)
    if not view.is_active:
        raise NotFoundError("user not found")
    async with container.session_factory() as session, session.begin():
        await audit.record(
            session,
            who.actor,
            "contact.reveal",
            "staff",
            view.id,
            after={"name": view.full_name},
        )
    return StaffContacts(
        id=view.id, phone=(view.phone or "").strip() or None, email=view.email.strip() or None
    )


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
