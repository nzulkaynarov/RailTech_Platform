"""Запись в переписку без хода агента: ответы обработчиков бота и сообщения сверх лимита.

Менеджер в CRM видит всё, что видел клиент (SPEC §9.2): контакты компании, смену
языка, «пришлите текстом», сообщения, на которые бот промолчал из-за rate-limit.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.consent import consent_required
from app.repositories import leads as repo
from app.services.conversation_support import current_lead
from app.services.conversation_types import Incoming, Outgoing
from app.services.settings import SettingsService


class RecordsMixin:
    """Часть `ConversationService`; лида не создаёт — пишет только в открытую переписку."""

    _sessions: async_sessionmaker[AsyncSession]
    _settings: SettingsService

    async def accepts_files(self, tg_user_id: int) -> bool:
        """Файлы клиента сохраняются в хранилище только после согласия (SPEC §6.4)."""
        cfg = await self._settings.get()
        async with self._sessions() as session:
            lead, conversation = await current_lead(session, tg_user_id)
            if lead is None or conversation is None or lead.erased_at is not None:
                return False
            return not consent_required(
                lead.consent_given_at, lead.consent_version, cfg.texts.consent_version
            )

    async def record_lead_message(
        self, inc: Incoming, meta: dict[str, Any] | None = None
    ) -> int | None:
        """Сообщение лида без ответа бота; возвращает id лида или None, если лида нет."""
        async with self._sessions() as session, session.begin():
            lead, conversation = await current_lead(session, inc.tg_user_id)
            if lead is None or conversation is None or lead.erased_at is not None:
                return None
            await repo.add_message(
                session,
                conversation_id=conversation.id,
                role="lead",
                text=inc.text,
                tg_message_id=inc.message_id,
                attachments=inc.attachments,
                meta=meta,
            )
            lead.last_lead_msg_at = datetime.now(UTC)
            return lead.id

    async def record_bot_replies(self, tg_user_id: int, outgoing: list[Outgoing]) -> None:
        """Детерминированные ответы обработчиков — в переписку с ролью `bot`."""
        pending = [item for item in outgoing if item.message_id is None and item.text]
        if not pending:
            return
        async with self._sessions() as session, session.begin():
            lead, conversation = await current_lead(session, tg_user_id)
            if lead is None or conversation is None or lead.erased_at is not None:
                return
            for item in pending:
                await repo.add_message(
                    session, conversation_id=conversation.id, role="bot", text=item.text
                )
            lead.last_bot_msg_at = datetime.now(UTC)
