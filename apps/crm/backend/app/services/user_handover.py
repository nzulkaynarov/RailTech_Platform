"""Передача работы уходящего сотрудника коллеге (ADR-0015), вынесена из `services/users.py`."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
        await reassign(session, user_id, None)  # лиды у бота и сделки — в общую очередь
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
    await reassign(session, user_id, to_user_id)
    await session.execute(
        update(Client).where(Client.owner_user_id == user_id).values(owner_user_id=to_user_id)
    )
    await audit.record(
        session,
        actor,
        "user.hand_over",
        "user",
        user_id,
        after={"to_user_id": to_user_id, "active_leads": leads},
    )


async def reassign(session: AsyncSession, user_id: int, to_user_id: int | None) -> None:
    """Все лиды с ответственным (и у бота — клиенты после сделки) и открытые сделки."""
    await session.execute(
        update(Lead)
        .where(Lead.assigned_user_id == user_id, Lead.erased_at.is_(None))
        .values(assigned_user_id=to_user_id)
    )
    await session.execute(
        update(Deal)
        .where(Deal.owner_user_id == user_id, Deal.stage == "open")
        .values(owner_user_id=to_user_id)
    )
