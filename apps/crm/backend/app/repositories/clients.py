"""Список клиентов для CRM: открытые сделки и последняя активность одним запросом."""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Lead


async def list_with_stats(
    session: AsyncSession, q: str | None, limit: int
) -> list[tuple[Client, int, datetime | None]]:
    """Клиенты по имени + число открытых сделок + последнее сообщение лида или менеджера."""
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
    if q:
        stmt = stmt.where(or_(Client.name.ilike(f"%{q}%"), Client.inn.ilike(f"%{q}%")))
    rows = (await session.execute(stmt.limit(limit))).all()
    return [(client, int(deals or 0), last) for client, deals, last in rows]
