"""Сообщения Telegram по событиям ERP: считаются в транзакции обработки, уходят после коммита.

Обработчик события (`ErpEventsService.apply`) кладёт сообщения в `erp_event_notices` той же
транзакцией, что и изменения зеркала. Отправка — отдельным шагом после коммита (`deliver`, его
вызывает `CrmBus.process_inbox`), поэтому:
* откат транзакции или автоповтор обработчика сообщений не задваивает (строка либо есть, либо нет);
* падение воркера между коммитом и отправкой сообщение не теряет — его досылает сборщик (`sweep`,
  раз в минуту) не позже суток: устаревшее «счёт выставлен» вредит;
* каждый адресат получает сообщение один раз даже при частичном сбое: ушедшие записываются в `sent`.
Постоянные отказы Telegram (бот заблокирован, чат не найден) повторов не вызывают; сетевые сбои,
лимиты и 5xx — повторяются сборщиком.

Сообщение клиенту «Заявка принята» (D1-9, SPEC-v3 §8) — бот, а если у клиента нет Telegram — письмо:
элемент с `email` уходит письмом тому, у кого не нашлось чата. Письмо ставит в очередь `MailService`
(повторы и итог — в `email_log`); ключ `"<номер>:mail"` в `sent` не даёт отправить его дважды. Итог
элементов с `track` записывается в `client_notices` для карточки клиента.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import notice_mail
from app.config import Settings
from app.models.auth import User
from app.models.integrations import ErpEventNotice
from app.services.mail import MailService
from app.services.mail_templates import RenderedEmail

logger = structlog.get_logger(__name__)

#: Неотправленное сообщение старше этого сборщик не досылает.
UNSENT_MAX_AGE = timedelta(hours=24)
#: Сообщение моложе этого сборщик не трогает: его отправит задача после обработки события.
SWEEP_AFTER = timedelta(seconds=60)
#: Аренда строки на время отправки: дольше таймаута Telegram, короче интервала сборщика.
LEASE = timedelta(seconds=45)
SWEEP_LIMIT = 100
SEND_TIMEOUT_S = 10
#: Запас аренды сверх «число отправок × таймаут».
LEASE_RESERVE_S = 30

BotProvider = Callable[[], Awaitable[Bot | None]]


@dataclass(frozen=True, slots=True)
class _Send:
    key: str
    chat_id: int
    text: str
    markup: InlineKeyboardMarkup | None
    track: str | None = None
    client_id: int = 0


@dataclass(frozen=True, slots=True)
class _Mail:
    key: str
    to: str
    template: str
    content: RenderedEmail
    client_id: int
    track: str | None


# (track, канал, статус, код ошибки, клиент) — итог для `client_notices`.
_Result = tuple[str, str, str, str | None, int]


@dataclass(frozen=True, slots=True)
class _Plan:
    sends: list[_Send]
    mails: list[_Mail]


def _lease_for(sends: int) -> timedelta:
    return max(LEASE, timedelta(seconds=sends * SEND_TIMEOUT_S + LEASE_RESERVE_S))


def _transient(exc: Exception) -> bool:
    """Сбой, который может пройти сам: сеть, лимит, 5xx Telegram. Остальное — отказ адресату."""
    return isinstance(
        exc,
        TelegramNetworkError | TelegramRetryAfter | TelegramServerError | OSError | TimeoutError,
    )


def _markup(buttons: list[list[str]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, url=url)] for label, url in buttons]
    )


class ErpEventNotices:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        bot_provider: BotProvider,
        config: Settings,
        mail: MailService | None = None,
    ) -> None:
        self._sessions = sessions
        self._bot_provider = bot_provider
        self._config = config
        self._mail = mail

    @staticmethod
    def add(session: AsyncSession, event_id: str, items: list[dict[str, Any]]) -> None:
        """Записать сообщения события в транзакции обработки (ключ — id события шины).

        Повторной записи по тому же id нет: обработка идёт в одной транзакции со статусом inbox,
        откат уносит и эту строку, а обработанное событие второй раз не выполняется.
        """
        session.add(ErpEventNotice(event_id=uuid.UUID(event_id), items=items, sent=[]))

    async def deliver(self, event_id: str) -> int:
        """Отправить сообщения события после коммита; возвращает число отправленных."""
        key = uuid.UUID(event_id)
        plan = await self._claim(key)
        if not plan.sends and not plan.mails:
            return 0
        done: list[str] = []
        results: list[_Result] = []
        retry = await self._telegram(event_id, plan.sends, done, results)
        for mail in plan.mails:
            outcome = await notice_mail.send(self._mail, mail.template, mail.to, mail.content)
            if outcome == "error":
                retry = True
                continue
            done.append(mail.key)
            if mail.track:
                skipped = outcome == "skipped"
                status = "skipped" if skipped else "queued"
                error = "smtp_not_configured" if skipped else None
                results.append((mail.track, "email", status, error, mail.client_id))
        await self._release(key, done, retry=retry, results=results)
        return len(done)

    async def _telegram(
        self, event_id: str, sends: list[_Send], done: list[str], results: list[_Result]
    ) -> bool:
        """Отправки в Telegram; True — что-то стоит повторить (сеть, лимит, бота нет)."""
        if not sends:
            return False
        bot = await self._bot_provider()
        if bot is None:
            return True
        retry = False
        for send in sends:
            try:
                await bot.send_message(
                    chat_id=send.chat_id,
                    text=send.text,
                    reply_markup=send.markup,
                    request_timeout=SEND_TIMEOUT_S,
                )
            except (TelegramAPIError, OSError, TimeoutError, ValueError) as exc:
                logger.warning(
                    "erp_event_telegram_failed",
                    event_id=event_id,
                    tg_user_id=send.chat_id,
                    error=type(exc).__name__,
                    transient=_transient(exc),
                )
                if _transient(exc):
                    retry = True
                    continue
                if send.track:
                    failed = (send.track, "telegram", "failed", "telegram_failed", send.client_id)
                    results.append(failed)
            else:
                if send.track:
                    results.append((send.track, "telegram", "sent", None, send.client_id))
            done.append(send.key)
        return retry

    async def sweep(self, limit: int = SWEEP_LIMIT) -> int:
        """Досылает сообщения, которые не ушли (воркер упал, бота не было, сеть); раз в минуту.

        Сообщения старше суток закрываются без отправки. Возвращает число отправленных.
        """
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(ErpEventNotice)
                .where(
                    ErpEventNotice.notified_at.is_(None),
                    ErpEventNotice.created_at < now - UNSENT_MAX_AGE,
                )
                .values(notified_at=now)
            )
            pending = list(
                await session.scalars(
                    select(ErpEventNotice.event_id)
                    .where(
                        ErpEventNotice.notified_at.is_(None),
                        ErpEventNotice.created_at < now - SWEEP_AFTER,
                    )
                    .order_by(ErpEventNotice.created_at)
                    .limit(limit)
                )
            )
        sent = 0
        for event_id in pending:
            sent += await self.deliver(str(event_id))
        if sent:
            logger.warning("erp_event_notices_swept", notified=sent)
        return sent

    async def _claim(self, key: uuid.UUID) -> _Plan:
        """Взять строку в аренду и посчитать, что ещё не отправлено. Пусто — слать нечего."""
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await session.get(ErpEventNotice, key, with_for_update=True)
            if row is None or row.notified_at is not None:
                return _Plan([], [])
            if row.lease_until is not None and row.lease_until > now:
                return _Plan([], [])  # сообщение шлёт параллельный воркер
            plan = await self._targets(session, row)
            if self._config.telegram_dry_run or await self._bot_provider() is None:
                # Бота нет или он выключен: Telegram дождётся сборщика (до суток), письма уходят
                # сразу.
                if plan.sends and not plan.mails:
                    return _Plan([], [])
                plan = _Plan([], plan.mails)
            if not plan.sends and not plan.mails:
                row.notified_at = now
                return plan
            # Аренда: все отправки по таймауту каждой + запас; сборщик не пошлёт то же дважды.
            row.lease_until = now + _lease_for(len(plan.sends) + len(plan.mails))
            return plan

    async def _release(
        self,
        key: uuid.UUID,
        done: list[str],
        *,
        retry: bool,
        results: list[_Result] | None = None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(ErpEventNotice, key, with_for_update=True)
            if row is None:
                return
            row.sent = [*row.sent, *done]
            row.lease_until = None
            if not retry:
                row.notified_at = datetime.now(UTC)
            for track, channel, status, error, client_id in results or []:
                await notice_mail.record(
                    session,
                    kind=track,
                    client_id=client_id,
                    channel=channel,
                    status=status,
                    error=error,
                    dedupe_key=f"{track}:{key}:{channel}:{client_id}",
                )

    async def _targets(self, session: AsyncSession, row: ErpEventNotice) -> _Plan:
        already = set(row.sent)
        sends: list[_Send] = []
        mails: list[_Mail] = []
        for index, item in enumerate(row.items):
            chats: list[int] = []
            markup: InlineKeyboardMarkup | None = None
            kind = item.get("kind")
            if kind == "client":
                markup = _markup(item.get("buttons") or [])
                chats = await notice_mail.client_chats(
                    session, item["client_id"], with_leads=bool(item.get("track"))
                )
            elif kind == "staff":
                tg_user_id = await session.scalar(
                    select(User.tg_user_id).where(
                        User.id == item["user_id"], User.is_active.is_(True)
                    )
                )
                chats = [tg_user_id] if tg_user_id else []
            for chat_id in chats:
                key = f"{index}:{chat_id}"
                if key not in already:
                    sends.append(
                        _Send(
                            key,
                            chat_id,
                            item["text"],
                            markup,
                            item.get("track"),
                            item.get("client_id", 0),
                        )
                    )
            if kind == "client" and item.get("email") and not chats:
                mail = await self._mail_for(session, index, item, already)
                if mail is not None:
                    mails.append(mail)
        return _Plan(sends, mails)

    @staticmethod
    async def _mail_for(
        session: AsyncSession, index: int, item: dict[str, Any], already: set[str]
    ) -> _Mail | None:
        """Письмо вместо бота: клиенту без Telegram, если есть куда писать и оно ещё не ушло."""
        key = f"{index}:mail"
        if key in already:
            return None
        to = await notice_mail.client_email(session, item["client_id"])
        if to is None:
            return None
        return _Mail(
            key,
            to,
            item.get("track") or "erp_event",
            notice_mail.rendered(item),
            item["client_id"],
            item.get("track"),
        )
