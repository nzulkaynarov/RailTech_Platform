"""Доступ к лидам, идентичностям, диалогам и сообщениям (SPEC §5.2–5.3)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clients import ServiceRequest
from app.models.deals import Deal
from app.models.email import EmailLog
from app.models.leads import Conversation, Lead, LeadNote, Message, TelegramIdentity
from app.models.notices import ClientNotice
from app.models.qualification import Escalation
from app.repositories import events

ERASED_TEXT = "[удалено по запросу]"


async def get_identity(session: AsyncSession, tg_user_id: int) -> TelegramIdentity | None:
    stmt = select(TelegramIdentity).where(TelegramIdentity.tg_user_id == tg_user_id)
    return (await session.scalars(stmt)).first()


async def chats_of_lead(session: AsyncSession, lead_id: int) -> list[int]:
    """Telegram-аккаунты лида (личный чат = `tg_user_id`) — для меню чата после действий CRM."""
    stmt = select(TelegramIdentity.tg_user_id).where(TelegramIdentity.lead_id == lead_id)
    return list((await session.scalars(stmt)).all())


async def chats_of_client(session: AsyncSession, client_id: int) -> list[int]:
    stmt = select(TelegramIdentity.tg_user_id).where(TelegramIdentity.client_id == client_id)
    return list((await session.scalars(stmt)).all())


async def get_lead(session: AsyncSession, lead_id: int, *, for_update: bool = False) -> Lead | None:
    stmt = select(Lead).where(Lead.id == lead_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


async def create_lead_with_identity(
    session: AsyncSession,
    *,
    tg_user_id: int,
    username: str | None,
    first_name: str | None,
    chat_id: int,
    language: str,
    identity: TelegramIdentity | None,
) -> tuple[Lead, TelegramIdentity, Conversation]:
    lead = Lead(display_name=(first_name or username or "")[:255], language=language)
    session.add(lead)
    await session.flush()
    if identity is None:
        identity = TelegramIdentity(tg_user_id=tg_user_id)
        session.add(identity)
    identity.tg_username = username
    identity.tg_first_name = first_name
    identity.lead_id = lead.id
    conversation = Conversation(lead_id=lead.id, tg_chat_id=chat_id)
    session.add(conversation)
    await session.flush()
    return lead, identity, conversation


async def open_conversation(session: AsyncSession, lead_id: int) -> Conversation | None:
    stmt = (
        select(Conversation)
        .where(Conversation.lead_id == lead_id, Conversation.is_open)
        .order_by(Conversation.id.desc())
    )
    return (await session.scalars(stmt)).first()


async def add_message(
    session: AsyncSession,
    *,
    conversation_id: int,
    role: str,
    text: str,
    tg_message_id: int | None = None,
    sent_by_user_id: int | None = None,
    attachments: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        text=text,
        tg_message_id=tg_message_id,
        sent_by_user_id=sent_by_user_id,
        attachments=attachments or [],
        meta=meta or {},
    )
    session.add(message)
    await session.flush()
    await events.publish_message(session, conversation_id, message.id, role)
    return message


async def recent_messages(session: AsyncSession, lead_id: int, limit: int) -> Sequence[Message]:
    stmt = (
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.lead_id == lead_id)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    return list(reversed((await session.scalars(stmt)).all()))


async def bot_notes(session: AsyncSession, lead_id: int, limit: int = 10) -> Sequence[LeadNote]:
    stmt = (
        select(LeadNote)
        .where(LeadNote.lead_id == lead_id, LeadNote.visible_to_bot)
        .order_by(LeadNote.id.desc())
        .limit(limit)
    )
    return list(reversed((await session.scalars(stmt)).all()))


async def attachment_keys(session: AsyncSession, lead_id: int) -> list[str]:
    """Ключи вложений лида в S3 — удаляются вместе с перепиской по /delete."""
    conversation_ids = select(Conversation.id).where(Conversation.lead_id == lead_id)
    rows = await session.scalars(
        select(Message.attachments).where(Message.conversation_id.in_(conversation_ids))
    )
    return [
        str(item["storage_key"])
        for attachments in rows
        for item in attachments or []
        if isinstance(item, dict) and item.get("storage_key")
    ]


async def close_escalations(session: AsyncSession, lead_id: int, now: datetime) -> list[int]:
    """Открытые и взятые эскалации лида закрываются: напоминать о них больше некому."""
    result = await session.scalars(
        update(Escalation)
        .where(Escalation.lead_id == lead_id, Escalation.status.in_(("open", "snoozed", "taken")))
        .values(status="closed", resolved_at=now, outcome="erased")
        .returning(Escalation.id)
    )
    return list(result.all())


async def erase_lead(session: AsyncSession, lead: Lead, now: datetime) -> int:
    """Обезличивание по запросу (/delete, SPEC §6.4). Возвращает число сообщений."""
    conversation_ids = select(Conversation.id).where(Conversation.lead_id == lead.id)
    result = await session.execute(
        update(Message)
        .where(Message.conversation_id.in_(conversation_ids))
        .values(text=ERASED_TEXT, attachments=[], meta=func.jsonb_build_object("erased", True))
    )
    await session.execute(
        update(TelegramIdentity)
        .where(TelegramIdentity.lead_id == lead.id)
        .values(tg_username=None, tg_first_name=None, phone_e164=None, lead_id=None)
    )
    await session.execute(
        update(Conversation).where(Conversation.lead_id == lead.id).values(is_open=False)
    )
    await session.execute(
        update(LeadNote).where(LeadNote.lead_id == lead.id).values(text=ERASED_TEXT)
    )
    await _erase_related(session, lead, now)
    lead.display_name = ""
    lead.snoozed_until = None
    lead.need_summary = None
    lead.qualification = {}
    lead.erased_at = now
    return int(getattr(result, "rowcount", 0) or 0)


async def _erase_related(session: AsyncSession, lead: Lead, now: datetime) -> None:
    """Сделки и запросы клиента тоже несут ПДн лида (аудит 2026-10-12, P1-9)."""
    # Подтверждения клиенту (D1-9): строка итога и письмо в журнале несут адрес и имя лида.
    log_ids = (
        await session.scalars(
            select(ClientNotice.email_log_id).where(
                ClientNotice.lead_id == lead.id, ClientNotice.email_log_id.is_not(None)
            )
        )
    ).all()
    await session.execute(delete(ClientNotice).where(ClientNotice.lead_id == lead.id))
    if log_ids:
        await session.execute(delete(EmailLog).where(EmailLog.id.in_(log_ids)))
    name = (lead.display_name or "").strip()
    if name:
        await session.execute(
            update(Deal)
            .where(Deal.lead_id == lead.id, Deal.title.contains(name, autoescape=True))
            .values(title=func.replace(Deal.title, name, f"Лид #{lead.id}"))
        )
    await session.execute(
        update(ServiceRequest)
        .where(ServiceRequest.lead_id == lead.id, ServiceRequest.status == "open")
        .values(status="closed", closed_at=now)
    )
    await session.execute(
        update(ServiceRequest)
        .where(ServiceRequest.lead_id == lead.id)
        .values(summary=ERASED_TEXT, resolution=None)
    )
