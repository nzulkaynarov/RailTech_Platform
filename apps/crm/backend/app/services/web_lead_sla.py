"""Срок первого ответа на запрос с сайта (D1-9, SPEC-v3 §9 «SLA лида истекает»).

Срок — `settings.web_form.first_response_sla_minutes` рабочих минут (Ташкент, `business_hours`),
ставится при приёме
запроса в `leads.first_response_due_at`. Пока лид без ответственного, срок «тикает»; взял менеджер
(появился
`assigned_user_id`) — запрос отвечен. Просрочку проверяет отложенная задача
(`tasks/client_notices.py`): один раз пишет
менеджерам и ставит `first_response_notified_at`, чтобы напоминание не повторялось.
"""

from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.business_hours import add_business_minutes
from app.models.leads import Lead
from app.repositories import events
from app.repositories import leads as repo
from app.schemas.settings import AppSettings

logger = structlog.get_logger(__name__)


def due_at(cfg: AppSettings, now: datetime) -> datetime:
    """Когда истекает срок первого ответа, считая от `now` по рабочим часам компании."""
    return add_business_minutes(
        now, cfg.web_form.first_response_sla_minutes, cfg.business_hours.domain()
    )


def awaiting(first_response_due_at: datetime | None, assigned_user_id: int | None) -> bool:
    """Запрос ждёт первого ответа: срок заведён, а ответственного нет."""
    return first_response_due_at is not None and assigned_user_id is None


def overdue(
    first_response_due_at: datetime | None, assigned_user_id: int | None, now: datetime
) -> bool:
    return awaiting(first_response_due_at, assigned_user_id) and (
        first_response_due_at is not None and first_response_due_at <= now
    )


async def mark_overdue(
    sessions: async_sessionmaker[AsyncSession], lead_id: int, now: datetime
) -> bool:
    """True — срок истёк, запрос никто не взял и об этом ещё не писали: отметка поставлена."""
    async with sessions() as session, session.begin():
        lead = await repo.get_lead(session, lead_id, for_update=True)
        if (
            lead is None
            or lead.erased_at is not None
            or lead.first_response_notified_at is not None
            or not overdue(lead.first_response_due_at, lead.assigned_user_id, now)
        ):
            return False
        lead.first_response_notified_at = now
        await events.publish(session, "lead.updated", lead_id=lead_id)
    logger.info("web_lead_sla_overdue", lead_id=lead_id)
    return True


async def overdue_ids(
    sessions: async_sessionmaker[AsyncSession], now: datetime, limit: int = 100
) -> list[int]:
    """Запросы с просроченным сроком, о которых ещё не писали и которые никто не взял.

    Страховка к отложенной задаче на конкретного лида: склейка карточек удаляет поглощённого лида,
    а срок переходит к выжившему (`lead_merge`), и задача, поставленная на старый id, ничего не
    находит. Периодический проход (`tasks/client_notices.py`) подхватывает такой срок.
    """
    async with sessions() as session:
        rows = await session.scalars(
            select(Lead.id)
            .where(
                Lead.first_response_due_at.is_not(None),
                Lead.first_response_due_at <= now,
                Lead.first_response_notified_at.is_(None),
                Lead.assigned_user_id.is_(None),
                Lead.erased_at.is_(None),
            )
            .order_by(Lead.id)
            .limit(limit)
        )
        return list(rows.all())
