"""Сообщение лиду от имени бота вне хода диалога (воркер: эскалации, таймеры)."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

import structlog
from aiogram.exceptions import TelegramNetworkError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, Reason
from app.models.leads import Conversation, Message
from app.repositories import crm as crm_repo
from app.repositories import leads as repo
from app.services import message_log

logger = structlog.get_logger(__name__)

# Ответ менеджера (D1-1): ждём Telegram меньше, чем BFF ждёт CRM (30 с) — экран получает итог,
# а не обрыв.
REPLY_TIMEOUT_S: Final = 20.0
# Ответ «отправляется» дольше этого — итог неизвестен (Telegram мог принять, а запись итога —
# упасть): повтор с тем же ключом не шлёт второе сообщение, а возвращает этот ответ.
STALE_SENDING: Final = timedelta(minutes=2)
SENDING: Final = "sending"
SENT: Final = "sent"


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
            message = await message_log.add(
                session,
                conversation,
                role=role,
                text=text,
                meta=meta or {},
                sent_by_user_id=sent_by_user_id,
                tg_message_id=getattr(sent, "message_id", None),
            )
            return message.id

    async def send_once(
        self, lead_id: int, text: str, key: str, *, sent_by_user_id: int
    ) -> int | None:
        """Ответ менеджера с ключом повтора — без дубля при параллельном повторе (`ReplyOnce`)."""
        return await ReplyOnce(self._sessions, self._sender).send(
            lead_id, text, key, sent_by_user_id=sent_by_user_id
        )


class ReplyOnce:
    """Ответ менеджера с ключом повтора: ключ занимается до отправки, поэтому параллельный повтор
    (обрыв у BFF, второй клик) не шлёт клиенту второе сообщение.

    1. Под транзакционной advisory-блокировкой на (лид, ключ) — поиск ответа с ключом и запись
       строки `meta.delivery = sending` (события шины ещё нет). Второй запрос ждёт блокировку и
       видит строку: `sending` — 409 `reply_in_progress`; `sent` или «зависшая» дольше
       `STALE_SENDING` — её id.
    2. Отправка в Telegram с таймаутом `REPLY_TIMEOUT_S`. Отказ Telegram — строка удаляется
       (не доставлено, повтор отправит заново). Таймаут или сетевой сбой — итог неизвестен: строка
       остаётся `sending`, повтор получает 409, после `STALE_SENDING` — считается отправленной.
    3. `delivery = sent` и событие `lead.message_added` — одной транзакцией. Если запись итога
       упала, а Telegram принял — строка остаётся `sending` с текстом (см. п. 2), дубля нет.
    """

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], sender: TextSender | None
    ) -> None:
        self._sessions = sessions
        self._sender = sender

    async def send(self, lead_id: int, text: str, key: str, *, sent_by_user_id: int) -> int | None:
        reserved = await self._reserve(lead_id, text, key, sent_by_user_id)
        if reserved is None or isinstance(reserved, int):
            return reserved
        message_id, chat_id = reserved
        assert self._sender is not None  # noqa: S101 — проверено при резерве
        try:
            sent = await asyncio.wait_for(self._sender.send_message(chat_id, text), REPLY_TIMEOUT_S)
        except (TimeoutError, TelegramNetworkError):
            logger.warning("lead_reply_unknown", lead_id=lead_id, message_id=message_id)
            return None
        except Exception:
            logger.exception("lead_reply_failed", lead_id=lead_id)
            await self._release(message_id)
            return None
        try:
            await self._confirm(message_id, getattr(sent, "message_id", None))
        except Exception:
            logger.exception("lead_reply_confirm_failed", lead_id=lead_id, message_id=message_id)
        return message_id

    async def _reserve(
        self, lead_id: int, text: str, key: str, sent_by_user_id: int
    ) -> int | tuple[int, int] | None:
        async with self._sessions() as session, session.begin():
            lock = func.hashtextextended(f"reply:{lead_id}:{key}", 0)
            await session.execute(select(func.pg_advisory_xact_lock(lock)))
            found = await crm_repo.reply_by_key(session, lead_id, key)
            if found is not None:
                fresh = found.created_at > datetime.now(UTC) - STALE_SENDING
                if (found.meta or {}).get("delivery") == SENDING and fresh:
                    raise ConflictError("reply is being sent", reason=Reason.REPLY_IN_PROGRESS)
                return found.id
            conversation = await repo.open_conversation(session, lead_id)
            if conversation is None or self._sender is None:
                logger.warning(
                    "lead_message_skipped", lead_id=lead_id, has_sender=bool(self._sender)
                )
                return None
            message = await repo.add_message(
                session,
                conversation_id=conversation.id,
                role="manager",
                text=text,
                meta={"mode": "manager", "client_message_id": key, "delivery": SENDING},
                sent_by_user_id=sent_by_user_id,
            )
            return message.id, conversation.tg_chat_id

    async def _release(self, message_id: int) -> None:
        async with self._sessions() as session, session.begin():
            message = await session.get(Message, message_id)
            if message is not None:
                await session.delete(message)

    async def _confirm(self, message_id: int, tg_message_id: int | None) -> None:
        async with self._sessions() as session, session.begin():
            message = await session.get(Message, message_id, with_for_update=True)
            if message is None:
                return
            message.meta = {**(message.meta or {}), "delivery": SENT}
            message.tg_message_id = tg_message_id
            conversation = await session.get(Conversation, message.conversation_id)
            if conversation is not None:
                await message_log.announce(session, conversation, message)


class DryRunSender:
    """Отправка без Telegram (e2e, демо): сообщение только логируется."""

    def __init__(self) -> None:
        self._counter = 0

    async def send_message(self, chat_id: int, text: str) -> Any:
        self._counter += 1
        logger.info("telegram_dry_run", chat_id=chat_id, length=len(text))
        return type("Sent", (), {"message_id": self._counter})()
