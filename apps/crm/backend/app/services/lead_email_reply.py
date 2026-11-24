"""Ответ менеджера лиду письмом (CH-1): с почты компании, запись в переписку лида `channel=email`.

Письмо идёт обычным путём `MailService.send_rendered` (очередь, журнал, ошибки подключения).
Повтор с тем же ключом второго письма не шлёт: ответ ищется по ключу под блокировкой лида.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, Reason
from app.models.leads import Conversation, Lead
from app.repositories import crm as crm_repo
from app.services import message_log
from app.services.mail import MailService
from app.services.mail_templates import RenderedEmail

EMAIL = "email"
TEMPLATE = "lead_reply"


async def _email_conversation(session: AsyncSession, lead_id: int) -> Conversation:
    stmt = (
        select(Conversation)
        .where(
            Conversation.lead_id == lead_id,
            Conversation.channel == EMAIL,
            Conversation.is_open,
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    found = (await session.scalars(stmt)).first()
    if found is not None:
        return found
    conversation = Conversation(lead_id=lead_id, channel=EMAIL, is_open=True)
    session.add(conversation)
    await session.flush()
    return conversation


async def send_reply(
    sessions: async_sessionmaker[AsyncSession],
    mail: MailService,
    lead_id: int,
    text: str,
    key: str | None,
    *,
    sent_by_user_id: int,
    on_behalf_of: int | None = None,
) -> int:
    """Письмо клиенту и сообщение в переписке одной транзакцией: без почты (409
    `smtp_not_configured`) сообщения в переписке не остаётся. Возвращает id сообщения."""
    async with sessions() as session, session.begin():
        if key is not None:
            lock = func.hashtextextended(f"reply:{lead_id}:{key}", 0)
            await session.execute(select(func.pg_advisory_xact_lock(lock)))
            found = await crm_repo.reply_by_key(session, lead_id, key)
            if found is not None:
                return found.id
        lead = await session.get(Lead, lead_id, with_for_update=True)
        if lead is None or not (lead.email or "").strip():
            raise ConflictError("lead has no e-mail", reason=Reason.NO_REPLY_CHANNEL)
        conversation = await _email_conversation(session, lead_id)
        meta: dict[str, Any] = {"mode": "manager", "channel": EMAIL, "delivery": "sent"}
        if key is not None:
            meta["client_message_id"] = key
        if on_behalf_of is not None:
            meta["on_behalf_of_user_id"] = on_behalf_of
        message = await message_log.add(
            session,
            conversation,
            role="manager",
            text=text,
            sent_by_user_id=sent_by_user_id,
            meta=meta,
        )
        sent = await mail.send_rendered(
            TEMPLATE,
            lead.email or "",
            RenderedEmail(subject=f"L-{lead_id:04d}", body=text, lang=lead.language),
            requested_by=sent_by_user_id,
            ref=("lead", str(lead_id)),
        )
        message.meta = {**message.meta, "email_log_id": sent.id}
        lead.last_human_msg_at = datetime.now(UTC)
        return message.id
