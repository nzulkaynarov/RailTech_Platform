"""Передача работы уходящего сотрудника коллеге (ADR-0015), вынесена из `services/users.py`."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.domain.errors import ActiveLeadsError, Reason, ValidationFailedError
from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Lead
from app.repositories import users as repo
from app.security import audit
from app.security.audit import Actor


async def hand_over_work(
    session: AsyncSession, actor: Actor, user_id: int, to_user_id: int | None
) -> None:
    """Лиды в работе и клиенты уходящего менеджера — коллеге; без коллеги деактивация запрещена."""
    leads = list(
        await session.scalars(
            select(Lead.id).where(
                Lead.assigned_user_id == user_id,
                Lead.owner_mode == "human",
                Lead.erased_at.is_(None),
            )
        )
    )
    if to_user_id is None:
        if leads:
            raise ActiveLeadsError("hand over the leads first", count=len(leads))
        # лиды у бота и сделки — в общую очередь
        await _publish(session, actor, await reassign(session, user_id, None), [])
        return
    target = await repo.get(session, to_user_id)
    roles = await repo.roles_of(session, to_user_id) if target else []
    inactive = target is None or to_user_id == user_id or not target.is_active
    if inactive or not {"manager", "admin"} & set(roles):
        raise ValidationFailedError(
            "choose an active colleague",
            reason=Reason.INACTIVE_COLLEAGUE,
            field="transfer_to_user_id",
        )
    changed_leads = await reassign(session, user_id, to_user_id)
    clients = await session.scalars(
        update(Client)
        .where(Client.owner_user_id == user_id)
        .values(owner_user_id=to_user_id)
        .returning(Client.id)
    )
    await _publish(session, actor, changed_leads, list(clients.all()))
    await audit.record(
        session,
        actor,
        "user.hand_over",
        "user",
        user_id,
        after={"to_user_id": to_user_id, "active_leads": leads},
    )


async def _publish(
    session: AsyncSession, actor: Actor, lead_ids: list[int], client_ids: list[int]
) -> None:
    """Массовая передача меняет ответственного у многих строк одним UPDATE: событие на каждую
    (подписчики применяют снимки; строки перечитываются — массовый UPDATE объекты не обновляет).
    """
    for lead_id in lead_ids:
        lead = await session.get(Lead, lead_id, populate_existing=True)
        if lead is not None:
            await bus_events.lead_updated(session, lead, actor, ["assigned_user"])
    for client_id in client_ids:
        client = await session.get(Client, client_id, populate_existing=True)
        if client is not None:
            await bus_events.client_updated(session, client, actor, ["owner"])


async def reassign(session: AsyncSession, user_id: int, to_user_id: int | None) -> list[int]:
    """Все лиды с ответственным (и у бота — клиенты после сделки) и открытые сделки.

    Возвращает id переданных лидов — по ним вызывающий публикует события.
    """
    moved = await session.scalars(
        update(Lead)
        .where(Lead.assigned_user_id == user_id, Lead.erased_at.is_(None))
        .values(assigned_user_id=to_user_id)
        .returning(Lead.id)
    )
    lead_ids = list(moved.all())
    await session.execute(
        update(Deal)
        .where(Deal.owner_user_id == user_id, Deal.stage == "open")
        .values(owner_user_id=to_user_id)
    )
    return lead_ids
