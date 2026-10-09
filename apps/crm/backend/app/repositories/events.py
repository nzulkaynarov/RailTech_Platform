"""События CRM для live-обновлений (SSE, SPEC §10.1) через PostgreSQL NOTIFY.

Публикация — в транзакции изменения: событие доставляется только после
коммита и только если он прошёл. Работает из любого процесса (api, worker).
Полезная нагрузка минимальна (типы и id) — фронт перечитывает данные по REST.
"""

import json
from typing import Final, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leads import Conversation

CHANNEL: Final = "crm_events"
EventType = Literal["message.created", "lead.updated", "escalation.updated"]


async def publish(session: AsyncSession, event: EventType, **data: object) -> None:
    payload = json.dumps({"type": event, **data}, ensure_ascii=False, default=str)
    await session.execute(select(func.pg_notify(CHANNEL, payload)))


async def publish_message(
    session: AsyncSession, conversation_id: int, message_id: int, role: str
) -> None:
    lead_id = await session.scalar(
        select(Conversation.lead_id).where(Conversation.id == conversation_id)
    )
    await publish(session, "message.created", lead_id=lead_id, message_id=message_id, role=role)
