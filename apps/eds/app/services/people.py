"""Сотрудники для ответов и событий: имена из проекции `employees`, директор по умолчанию, проверка исполнителей."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import any_, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee
from app.schemas.common import PersonRef


@dataclass
class Directory:
    """Имена сотрудников, загруженные одним запросом. Нет в проекции или «надгробие» — `Сотрудник #id`."""

    names: dict[int, str] = field(default_factory=dict)

    def name(self, crm_user_id: int) -> str:
        return self.names.get(crm_user_id) or f"Сотрудник #{crm_user_id}"

    def person(self, crm_user_id: int) -> PersonRef:
        return PersonRef(crm_user_id=crm_user_id, full_name=self.name(crm_user_id))

    def person_or_none(self, crm_user_id: int | None) -> PersonRef | None:
        return None if crm_user_id is None else self.person(crm_user_id)


async def load_directory(session: AsyncSession, ids: Iterable[int | None]) -> Directory:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return Directory()
    rows = await session.execute(
        select(Employee.crm_user_id, Employee.full_name).where(Employee.crm_user_id.in_(wanted))
    )
    return Directory({int(uid): name for uid, name in rows.all()})


async def default_director(session: AsyncSession) -> int | None:
    """Директор по умолчанию (адресат письма без указания): активный сотрудник с `letters.resolve`, меньший id."""
    row = await session.execute(
        select(Employee.crm_user_id)
        .where(Employee.is_active.is_(True), literal("letters.resolve") == any_(Employee.permissions_eds))
        .order_by(Employee.crm_user_id)
        .limit(1)
    )
    return row.scalar_one_or_none()


async def active_ids(session: AsyncSession, ids: Iterable[int]) -> set[int]:
    """Какие из `ids` — активные сотрудники проекции."""
    wanted = set(ids)
    if not wanted:
        return set()
    rows = await session.execute(
        select(Employee.crm_user_id).where(Employee.crm_user_id.in_(wanted), Employee.is_active.is_(True))
    )
    return {int(i) for i in rows.scalars()}


async def holds_permission(session: AsyncSession, crm_user_id: int, permission: str) -> bool:
    row = await session.execute(
        select(Employee.crm_user_id).where(
            Employee.crm_user_id == crm_user_id,
            Employee.is_active.is_(True),
            literal(permission) == any_(Employee.permissions_eds),
        )
    )
    return row.scalar_one_or_none() is not None
