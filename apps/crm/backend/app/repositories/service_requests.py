"""Чтение сервисных запросов клиентов для CRM (Q-017: список во «Входящих», ссылка в карточке)."""

from typing import Literal

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import test_scope
from app.models.clients import Client, ServiceRequest
from app.models.leads import Lead

RequestStatus = Literal["open", "closed"]


def _visible() -> tuple[ColumnElement[bool], ...]:
    return () if test_scope.show_all() else (Client.is_test.is_(False),)  # ТЕСТ-2


async def list_with_clients(
    session: AsyncSession, status: RequestStatus, limit: int
) -> list[tuple[ServiceRequest, str]]:
    """Запросы с именем клиента; открытые — кто ждёт дольше, первыми; закрытые — свежие первыми."""
    order = ServiceRequest.id.asc() if status == "open" else ServiceRequest.id.desc()
    stmt = (
        select(ServiceRequest, Client.name)
        .join(Client, Client.id == ServiceRequest.client_id)
        .where(ServiceRequest.status == status, *_visible())  # ТЕСТ-1
        .order_by(order)
        .limit(limit)
    )
    return [(row, name) for row, name in (await session.execute(stmt)).all()]


async def open_request_id(session: AsyncSession, lead: Lead) -> int | None:
    """Последний открытый запрос этого лида или его клиента — для ссылки из карточки лида."""
    match = ServiceRequest.lead_id == lead.id
    if lead.client_id is not None:
        match = or_(match, ServiceRequest.client_id == lead.client_id)
    stmt = (
        select(ServiceRequest.id)
        .where(ServiceRequest.status == "open", match)
        .order_by(ServiceRequest.id.desc())
        .limit(1)
    )
    value: int | None = await session.scalar(stmt)
    return value
