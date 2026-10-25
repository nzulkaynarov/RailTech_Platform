"""Проекция сотрудников: идемпотентное применение снимков CRM и выборка для проверки доступа."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.snapshots import UserSnapshot
from app.models import Employee


async def apply_snapshot(session: AsyncSession, snapshot: UserSnapshot, *, event_id: uuid.UUID) -> bool:
    """Применить снимок `user.created|updated`. Более старый, чем уже сохранённый, не применяется (L11).

    Возвращает `True`, если строка записана. Повтор того же снимка безвреден.
    """
    values = {
        "crm_user_id": snapshot.crm_user_id,
        "email": snapshot.email,
        "full_name": snapshot.full_name,
        "position": snapshot.position,
        "language": snapshot.language,
        "is_active": snapshot.is_active,
        "permissions_eds": snapshot.permissions_eds,
        "updated_at": snapshot.updated_at,
        "last_event_id": event_id,
    }
    stmt = insert(Employee).values(**values)
    upsert = stmt.on_conflict_do_update(
        index_elements=[Employee.crm_user_id],
        set_={k: stmt.excluded[k] for k in values if k != "crm_user_id"} | {"synced_at": func.now()},
        where=Employee.updated_at <= stmt.excluded.updated_at,
    ).returning(Employee.crm_user_id)
    return (await session.execute(upsert)).first() is not None


async def apply_deactivation(session: AsyncSession, crm_user_id: int, *, at: datetime, event_id: uuid.UUID) -> bool:
    """Применить `user.deactivated`. Нет строки — «надгробие»: запоздавший старый снимок доступа не вернёт."""
    stmt = insert(Employee).values(
        crm_user_id=crm_user_id,
        email="",
        full_name="",
        is_active=False,
        permissions_eds=[],
        updated_at=at,
        last_event_id=event_id,
    )
    upsert = stmt.on_conflict_do_update(
        index_elements=[Employee.crm_user_id],
        set_={
            "is_active": False,
            "updated_at": stmt.excluded.updated_at,
            "last_event_id": stmt.excluded.last_event_id,
            "synced_at": func.now(),
        },
        where=Employee.updated_at <= stmt.excluded.updated_at,
    ).returning(Employee.crm_user_id)
    return (await session.execute(upsert)).first() is not None


async def get_employee(session: AsyncSession, crm_user_id: int) -> Employee | None:
    return (await session.execute(select(Employee).where(Employee.crm_user_id == crm_user_id))).scalar_one_or_none()
