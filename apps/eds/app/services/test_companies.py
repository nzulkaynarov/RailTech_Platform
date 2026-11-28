"""Тестовые компании в EDS (ТЕСТ-1): проекция отметки `is_test` из `erp.company.updated`, выборки «без тестовых».

Снимок несёт отметку целиком; более старый снимок (`company.updated_at`) значение не перезаписывает, снимок без поля
(прежний издатель) — не меняет. Реестр «Все документы» и список входящих писем скрывают документы тестовых компаний по
умолчанию (`?test=only` — только они, `?test=all` — все); открытие по номеру и карточка не сужаются.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import ColumnElement, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_companies import CompanyMark

ONLY = "only"
ALL = "all"


class _Tolerant(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CompanyMarkIn(_Tolerant):
    updated_at: AwareDatetime
    is_test: bool | None = None


class CompanyUpdated(_Tolerant):
    """`data` события `uz.railtech.erp.company.updated.v1`: только то, что читает EDS."""

    erp_company_id: int
    company: CompanyMarkIn


async def apply(session: AsyncSession, data: CompanyUpdated) -> bool:
    """Записать отметку; `False` — снимок старый или без поля `is_test`."""
    if data.company.is_test is None:
        return False
    at: datetime = data.company.updated_at
    values = {"erp_company_id": data.erp_company_id, "is_test": data.company.is_test, "snapshot_at": at}
    insertion = insert(CompanyMark).values(**values)
    stmt = insertion.on_conflict_do_update(
        index_elements=[CompanyMark.erp_company_id],
        set_={"is_test": insertion.excluded.is_test, "snapshot_at": insertion.excluded.snapshot_at},
        where=CompanyMark.snapshot_at < insertion.excluded.snapshot_at,
    ).returning(CompanyMark.erp_company_id)
    return (await session.execute(stmt)).first() is not None


def mode(params: Mapping[str, Any] | str | None) -> str:
    value = params if isinstance(params, str) or params is None else params.get("test")
    return value if value in (ONLY, ALL) else ""


async def marked(session: AsyncSession, wanted: str | None, ids: Iterable[int | None]) -> frozenset[int]:
    """ТЕСТ-2: тестовые компании среди `ids` строк страницы — для метки «Тестовая».

    Только при `?test=all` или `only`: без параметра тестовых строк в выдаче нет, запрос не нужен."""
    if not mode(wanted):
        return frozenset()
    found = {i for i in ids if i is not None}
    if not found:
        return frozenset()
    rows = await session.scalars(
        select(CompanyMark.erp_company_id).where(CompanyMark.erp_company_id.in_(found), CompanyMark.is_test.is_(True))
    )
    return frozenset(rows)


def scope(column: Any, wanted: str | None) -> ColumnElement[bool] | None:
    """Условие по колонке `erp_company_id`: без параметра — не тестовая (компании без отметки и без компании проходят),
    `only` — только тестовые, `all` — без условия."""
    chosen = mode(wanted)
    if chosen == ALL:
        return None
    tests = select(CompanyMark.erp_company_id).where(CompanyMark.is_test.is_(True))
    inside: ColumnElement[bool] = column.in_(tests)
    if chosen == ONLY:
        return inside
    outside: ColumnElement[bool] = column.is_(None) | column.not_in(tests)
    return outside
