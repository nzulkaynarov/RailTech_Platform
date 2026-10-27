"""Запись сообщения в переписку лида вместе с событием шины (D1-1).

Каждое сообщение переписки — входящее от лида и исходящее от бота или менеджера — пишется
здесь: строка `messages` и строка outbox `uz.railtech.crm.lead.message_added.v1` уходят одной
транзакцией вызывающего (правило «события только через rt_bus из сервисного слоя»,
`CONVENTIONS.md §11`). Откат транзакции убирает и сообщение, и событие; ошибка публикации
откатывает сообщение. Текста в событии нет: Платформа получает подсказку и перезапрашивает
переписку API CRM с правами сотрудника.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import events as bus_events
from app.models.leads import Conversation, Lead, Message
from app.repositories import leads as repo
from app.security.audit import Actor


def _actor(role: str, sent_by_user_id: int | None) -> Actor:
    if role == "manager" and sent_by_user_id is not None:
        return Actor(sent_by_user_id, "user")
    return Actor(None, "bot")


async def add(
    session: AsyncSession,
    conversation: Conversation,
    *,
    role: str,
    text: str,
    tg_message_id: int | None = None,
    sent_by_user_id: int | None = None,
    attachments: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> Message:
    """Сообщение в переписку и событие о нём; вызывать внутри `async with session.begin()`."""
    message = await repo.add_message(
        session,
        conversation_id=conversation.id,
        role=role,
        text=text,
        tg_message_id=tg_message_id,
        sent_by_user_id=sent_by_user_id,
        attachments=attachments,
        meta=meta,
    )
    lead = await session.get(Lead, conversation.lead_id)
    if lead is not None:
        await bus_events.lead_message_added(
            session,
            lead,
            message,
            channel=conversation.channel or "telegram",
            sent_at=datetime.now(UTC),
            actor=_actor(role, sent_by_user_id),
        )
    return message
