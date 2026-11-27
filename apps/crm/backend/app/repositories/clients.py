"""Список клиентов для CRM: открытые сделки и последняя активность одним запросом."""

from datetime import datetime
from typing import Literal

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Lead

TestScope = Literal["only", "all"]


def test_scope(scope: TestScope | None) -> ColumnElement[bool] | None:
    """ТЕСТ-1: без параметра тестовых нет, `only` — только они, `all` — все вместе (`None`)."""
    if scope == "all":
        return None
    return Client.is_test.is_(True) if scope == "only" else Client.is_test.is_(False)


async def list_with_stats(
    session: AsyncSession, q: str | None, limit: int, test: TestScope | None = None
) -> list[tuple[Client, int, datetime | None]]:
    """Клиенты по имени + число открытых сделок + последнее сообщение лида или менеджера.

    Тестовые компании (ТЕСТ-1) — только по `test=only` или `test=all`."""
    open_deals = (
        select(func.count(Deal.id))
        .where(Deal.client_id == Client.id, Deal.stage == "open")
        .correlate(Client)
        .scalar_subquery()
    )
    last_activity = (
        select(func.max(func.greatest(Lead.last_lead_msg_at, Lead.last_human_msg_at)))
        .where(Lead.client_id == Client.id)
        .correlate(Client)
        .scalar_subquery()
    )
    stmt = select(Client, open_deals, last_activity).order_by(Client.name)
    scope = test_scope(test)
    if scope is not None:
        stmt = stmt.where(scope)
    if q:
        stmt = stmt.where(or_(Client.name.ilike(f"%{q}%"), Client.inn.ilike(f"%{q}%")))
    rows = (await session.execute(stmt.limit(limit))).all()
    return [(client, int(deals or 0), last) for client, deals, last in rows]
