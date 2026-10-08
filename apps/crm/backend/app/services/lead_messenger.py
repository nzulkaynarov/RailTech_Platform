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

    async def send(
        self,
        lead_id: int,
        text: str,
        meta: dict[str, Any] | None = None,
        *,
        role: str = "bot",
        sent_by_user_id: int | None = None,
    ) -> int | None:
        """Отправить в открытый чат лида и сохранить в истории. None — не отправлено."""
        async with self._sessions() as session:
            conversation = await repo.open_conversation(session, lead_id)
        if conversation is None or self._sender is None:
            logger.warning("lead_message_skipped", lead_id=lead_id, has_sender=bool(self._sender))
            return None
        try:
            sent = await self._sender.send_message(conversation.tg_chat_id, text)
        except Exception:
            logger.exception("lead_message_failed", lead_id=lead_id)
            return None
        async with self._sessions() as session, session.begin():
            message = await repo.add_message(
                session,
                conversation_id=conversation.id,
                role=role,
                text=text,
                meta=meta or {},
                sent_by_user_id=sent_by_user_id,
                tg_message_id=getattr(sent, "message_id", None),
            )
            return message.id


class DryRunSender:
    """Отправка без Telegram (e2e, демо): сообщение только логируется."""

    def __init__(self) -> None:
        self._counter = 0

    async def send_message(self, chat_id: int, text: str) -> Any:
        self._counter += 1
        logger.info("telegram_dry_run", chat_id=chat_id, length=len(text))
        return type("Sent", (), {"message_id": self._counter})()
