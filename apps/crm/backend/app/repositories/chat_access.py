"""Факты для доступа к переписке (B-D18-1): участвует ли сотрудник в диалоге, выставлен ли счёт.

Правило — `app/domain/chat_access.py`; здесь только SQL. Сделки диалога — сделки этого лида
(`deals.lead_id`) и сделки его клиента (`deals.client_id`): заявки клиента из кабинета и ERP
привязываются к клиенту, а переписка с ним — одна.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, and_, exists, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.chat_access import DialogFacts
from app.domain.sandbox import SANDBOX_SOURCE
from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Conversation, Lead, Message


def _deal_of_lead() -> ColumnElement[bool]:
    return or_(
        Deal.lead_id == Lead.id,
        and_(Lead.client_id.is_not(None), Deal.client_id == Lead.client_id),
    )


def participant(user_id: int) -> ColumnElement[bool]:
    """Сотрудник участвует в диалоге: ответственный за лида, клиента или сделку, автор ответа."""
    wrote = exists().where(
        Conversation.lead_id == Lead.id,
        Message.conversation_id == Conversation.id,
        Message.sent_by_user_id == user_id,
    )
    owns_deal = exists().where(_deal_of_lead(), Deal.owner_user_id == user_id)
    owns_client = exists().where(Client.id == Lead.client_id, Client.owner_user_id == user_id)
    return or_(Lead.assigned_user_id == user_id, wrote, owns_deal, owns_client)


def invoiced() -> ColumnElement[bool]:
    """По сделке диалога ERP выставила счёт (`deals.invoice_issued_at`)."""
    return exists().where(_deal_of_lead(), Deal.invoice_issued_at.is_not(None))


async def dialog_facts(session: AsyncSession, lead_id: int, user_id: int) -> DialogFacts | None:
    """Факты по диалогу лида; нет лида, он обезличен или из песочницы — `None` (как в списке)."""
    row = (
        await session.execute(
            select(participant(user_id).label("participant"), invoiced().label("invoiced"))
            .select_from(Lead)
            .where(Lead.id == lead_id, Lead.erased_at.is_(None), Lead.source != SANDBOX_SOURCE)
        )
    ).one_or_none()
    if row is None:
        return None
    return DialogFacts(participant=bool(row.participant), invoiced=bool(row.invoiced))


@dataclass(frozen=True, slots=True)
class DialogScope:
    """Кто смотрит список: сотрудник и его права (реестр — все диалоги; зона счетов)."""

    user_id: int
    registry: bool
    invoiced_zone: bool


async def list_dialogs(
    session: AsyncSession,
    scope: DialogScope,
    *,
    client_id: int | None,
    erp_deal_id: int | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Lead, DialogFacts]], int]:
    """Диалоги, открытые сотруднику по правилу `domain/chat_access`, новые сверху, с фактами."""
    is_participant = participant(scope.user_id)
    has_invoice = invoiced()
    zone = has_invoice if scope.invoiced_zone else false()
    visible = true() if scope.registry else or_(is_participant, zone)
    stmt = select(Lead, is_participant.label("participant"), has_invoice.label("invoiced")).where(
        Lead.erased_at.is_(None), Lead.source != SANDBOX_SOURCE, visible
    )
    if client_id is not None:
        stmt = stmt.where(Lead.client_id == client_id)
    if erp_deal_id is not None:
        stmt = stmt.where(exists().where(_deal_of_lead(), Deal.erp_deal_id == erp_deal_id))
    total = int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = await session.execute(
        stmt.order_by(Lead.last_lead_msg_at.desc().nulls_last(), Lead.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        (lead, DialogFacts(participant=bool(part), invoiced=bool(inv)))
        for lead, part, inv in rows.all()
    ], total


def last_activity(lead: Lead) -> datetime | None:
    """Последнее сообщение диалога (клиента, бота или сотрудника)."""
    moments = (lead.last_lead_msg_at, lead.last_bot_msg_at, lead.last_human_msg_at)
    present = [moment for moment in moments if moment is not None]
    return max(present) if present else None
