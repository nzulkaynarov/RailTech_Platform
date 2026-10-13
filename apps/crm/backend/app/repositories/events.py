"""События CRM для live-обновлений (SSE, SPEC §10.1) через PostgreSQL NOTIFY.

Публикация — в транзакции изменения: событие доставляется только после
коммита и только если он прошёл. Работает из любого процесса (api, worker).
Полезная нагрузка минимальна (типы и id) — фронт перечитывает данные по REST.
"""

import json
from typing import Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leads import Conversation, Lead

CHANNEL: Final = "crm_events"
EventType = Literal["message.created", "lead.updated", "escalation.updated"]


async def publish(session: AsyncSession, event: EventType, **data: object) -> None:
    payload = json.dumps({"type": event, **data}, ensure_ascii=False, default=str)
    await session.execute(select(func.pg_notify(CHANNEL, payload)))


async def publish_message(
    session: AsyncSession, conversation_id: int, message_id: int, role: str
) -> None:
    """`assigned_user_id` — чтобы вкладка ответственного менеджера подала звук (Q-010)."""
    row = (
        await session.execute(
            select(Conversation.lead_id, Lead.assigned_user_id)
            .join(Lead, Lead.id == Conversation.lead_id)
            .where(Conversation.id == conversation_id)
        )
    ).first()
    lead_id, assigned = (row[0], row[1]) if row is not None else (None, None)
    await publish(
        session,
        "message.created",
        lead_id=lead_id,
        message_id=message_id,
        role=role,
        assigned_user_id=assigned,
    )
