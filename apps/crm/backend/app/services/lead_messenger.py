"""Сообщение лиду от имени бота вне хода диалога (воркер: эскалации, таймеры)."""

from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories import leads as repo

logger = structlog.get_logger(__name__)


class TextSender(Protocol):
    async def send_message(self, chat_id: int, text: str) -> Any: ...


class LeadMessenger:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], sender: TextSender | None
    ) -> None:
        self._sessions = sessions
        self._sender = sender

    async def send(self, lead_id: int, text: str, meta: dict[str, Any] | None = None) -> bool:
        """Отправить в открытый чат лида и сохранить в истории. False — не отправлено."""
        async with self._sessions() as session:
            conversation = await repo.open_conversation(session, lead_id)
        if conversation is None or self._sender is None:
            logger.warning("lead_message_skipped", lead_id=lead_id, has_sender=bool(self._sender))
            return False
        try:
            await self._sender.send_message(conversation.tg_chat_id, text)
        except Exception:
            logger.exception("lead_message_failed", lead_id=lead_id)
            return False
        async with self._sessions() as session, session.begin():
            await repo.add_message(
                session, conversation_id=conversation.id, role="bot", text=text, meta=meta or {}
            )
        return True
