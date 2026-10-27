"""Подтверждение запроса клиенту и итог отправки (D1-9, SPEC-v3 §3.1 шаг 1 и §8).

Форма «Я новый клиент» создаёт лида; клиенту должно прийти подтверждение: в Telegram, если у запроса
есть чат с ботом
(повторный запрос от известного клиента), иначе письмо. Запрос с одним телефоном подтвердить нечем —
строка получает
статус `skipped` с причиной `no_channel`, и менеджер видит это в карточке (позвонить).

Строка `client_notices` создаётся в транзакции приёма запроса (`plan_web_confirmation`), отправка —
задача очереди
(`tasks/client_notices.py` → `deliver`): запрос с сайта не ждёт ни почты, ни Telegram. Временный
сбой Telegram повторяется
задачей; постоянный отказ (бот заблокирован) или исчерпанные попытки переводят отправку на письмо,
если у лида есть адрес.
Итог письма читается из `email_log` (`view`): письмо уходит своей задачей `send_email`, и его статус
— там.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain import client_texts
from app.domain.errors import ConflictError, Reason
from app.domain.notice_errors import error_text
from app.domain.start_link import issue_lead_link
from app.models.email import EmailLog
from app.models.leads import Lead, TelegramIdentity
from app.models.notices import ClientNotice
from app.repositories import leads as repo
from app.services.mail import MailService
from app.services.mail_templates import RenderedEmail
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

MAX_TELEGRAM_ATTEMPTS: Final = 4
SEND_TIMEOUT_S: Final = 10
WEB_CONFIRMATION: Final = "web_confirmation"
BotProvider = Callable[[], Awaitable[Bot | None]]
BotUsername = Callable[[], Awaitable[str | None]]


@dataclass(frozen=True, slots=True)
class NoticeView:
    """Итог для карточки: статус с учётом письма в `email_log`, причина кодом и словами."""

    id: int
    kind: str
    channel: str
    status: str
    error: str | None
    error_text: str | None
    created_at: datetime
    sent_at: datetime | None
    detail: dict[str, object]


def _transient(exc: Exception) -> bool:
    return isinstance(
        exc,
        TelegramNetworkError | TelegramRetryAfter | TelegramServerError | OSError | TimeoutError,
    )


def web_confirmation_key(lead_id: int, request_id: int | None = None) -> str:
    """Один запрос с сайта — одно подтверждение; повтор того же запроса (двойная отправка) не
    дублирует."""
    return f"{WEB_CONFIRMATION}:{lead_id}:{request_id or 0}"


class ClientNoticeService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        mail: MailService,
        bot_provider: BotProvider,
        bot_username: BotUsername,
        form_key: bytes,
        config: Settings,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._mail = mail
        self._bot_provider = bot_provider
        self._bot_username = bot_username
        self._key = form_key
        self._config = config

    # --- планирование: в транзакции приёма запроса -------------------------------------------

    async def plan_web_confirmation(
        self, session: AsyncSession, lead: Lead, request_id: int | None = None
    ) -> ClientNotice | None:
        """Строка подтверждения в транзакции приёма; `None` — такой запрос уже подтверждён."""
        key = web_confirmation_key(lead.id, request_id)
        if await session.scalar(select(ClientNotice.id).where(ClientNotice.dedupe_key == key)):
            return None
        has_telegram = bool(
            await session.scalar(
                select(TelegramIdentity.id).where(
                    TelegramIdentity.lead_id == lead.id, TelegramIdentity.is_blocked.is_(False)
                )
            )
        )
        if has_telegram:
            channel, status, error = "telegram", "queued", None
        elif lead.email:
            channel, status, error = "email", "queued", None
        else:
            channel, status, error = "none", "skipped", "no_channel"
        notice = ClientNotice(
            kind=WEB_CONFIRMATION,
            lead_id=lead.id,
            channel=channel,
            status=status,
            error=error,
            dedupe_key=key,
        )
        session.add(notice)
        await session.flush()
        return notice

    # --- отправка: задача очереди ----------------------------------------------------------

    async def deliver(self, notice_id: int) -> str:
        """Отправить подтверждение; исключение — повторит задача (временный сбой Telegram)."""
        async with self._sessions() as session:
            notice = await session.get(ClientNotice, notice_id)
            if notice is None or notice.status != "queued" or notice.lead_id is None:
                return "skipped"
            if notice.email_log_id is not None:
                return "skipped"  # письмо уже у почтовой очереди; повтор задачи второго не шлёт
            lead = await session.get(Lead, notice.lead_id)
            channel, attempts = notice.channel, notice.attempts
            identity = await session.scalar(
                select(TelegramIdentity)
                .where(
                    TelegramIdentity.lead_id == notice.lead_id,
                    TelegramIdentity.is_blocked.is_(False),
                )
                .order_by(TelegramIdentity.id)
                .limit(1)
            )
        if lead is None or lead.erased_at is not None:
            await self._finish(notice_id, "skipped", "no_channel")
            return "skipped"
        if channel == "telegram":
            outcome = await self._via_telegram(notice_id, lead, identity, attempts)
            if outcome is not None:
                return outcome
        # Telegram не годится (постоянный отказ) или канал — письмо: запасной путь.
        return await self._via_email(notice_id, lead)

    async def _via_telegram(
        self, notice_id: int, lead: Lead, identity: TelegramIdentity | None, attempts: int
    ) -> str | None:
        """Исход (`sent`/`failed`) или `None` — Telegram не годится, пробуем письмо."""
        bot = await self._bot_provider()
        if identity is None or bot is None:
            return await self._fallback(
                notice_id, lead, "no_telegram" if bot else "bot_not_configured"
            )
        text = client_texts.web_confirmation_bot(lead.language, lead.display_name)
        if self._config.telegram_dry_run:
            logger.info("client_notice_dry_run", notice_id=notice_id, kind=WEB_CONFIRMATION)
        else:
            try:
                sent = await bot.send_message(
                    identity.tg_user_id, text, request_timeout=SEND_TIMEOUT_S
                )
            except TelegramForbiddenError:
                return await self._fallback(notice_id, lead, "telegram_blocked")
            except (TelegramAPIError, OSError, TimeoutError) as exc:
                if _transient(exc) and attempts + 1 < MAX_TELEGRAM_ATTEMPTS:
                    await self._bump(notice_id)
                    raise
                logger.warning(
                    "client_notice_telegram_failed", notice_id=notice_id, error=type(exc).__name__
                )
                return await self._fallback(notice_id, lead, "telegram_failed")
            await self._remember(lead.id, text, getattr(sent, "message_id", None))
        await self._finish(notice_id, "sent", None)
        return "sent"

    async def _fallback(self, notice_id: int, lead: Lead, code: str) -> str | None:
        """Запасной путь: письмо, если есть адрес; иначе сбой с причиной Telegram."""
        if lead.email:
            await self._finish(
                notice_id, "queued", None, channel="email", note={"telegram_failed": code}
            )
            return None
        await self._finish(notice_id, "failed", code)
        return "failed"

    async def _via_email(self, notice_id: int, lead: Lead) -> str:
        if not lead.email:
            await self._finish(notice_id, "skipped", "no_channel", channel="none")
            return "skipped"
        cfg = await self._settings.get()
        username = await self._bot_username()
        start = issue_lead_link(self._key, lead.id, datetime.now(UTC))
        link = f"https://t.me/{username}?start={start}" if username else None
        mail = client_texts.web_confirmation_mail(
            lead.language, lead.display_name, lead.need_summary, cfg.company.name, link
        )
        try:
            logged = await self._mail.send_rendered(
                WEB_CONFIRMATION,
                lead.email,
                RenderedEmail(mail.subject, mail.body, client_texts.lang(lead.language)),
            )
        except ConflictError as exc:
            reason = exc.details.get("reason")
            code = (
                Reason.SECRETS_KEY_MISSING.value
                if reason == Reason.SECRETS_KEY_MISSING
                else Reason.SMTP_NOT_CONFIGURED.value
            )
            await self._finish(notice_id, "skipped", code, channel="email")
            return "skipped"
        except Exception:
            logger.exception("client_notice_email_failed", notice_id=notice_id)
            await self._finish(notice_id, "failed", "email_failed", channel="email")
            return "failed"
        async with self._sessions() as session, session.begin():
            notice = await session.get(ClientNotice, notice_id, with_for_update=True)
            if notice is not None:
                notice.channel, notice.email_log_id = "email", logged.id
        return "queued"

    # --- запись состояния ---------------------------------------------------------------------

    async def _finish(
        self,
        notice_id: int,
        status: str,
        error: str | None,
        *,
        channel: str | None = None,
        note: dict[str, object] | None = None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            notice = await session.get(ClientNotice, notice_id, with_for_update=True)
            if notice is None:
                return
            notice.status, notice.error = status, error
            if channel is not None:
                notice.channel = channel
            if note:
                notice.detail = {**notice.detail, **note}
            if status == "sent":
                notice.sent_at = datetime.now(UTC)

    async def _bump(self, notice_id: int) -> None:
        async with self._sessions() as session, session.begin():
            notice = await session.get(ClientNotice, notice_id, with_for_update=True)
            if notice is not None:
                notice.attempts += 1

    async def _remember(self, lead_id: int, text: str, tg_message_id: int | None) -> None:
        """Сообщение бота — в историю лида, чтобы менеджер видел, что клиенту написано."""
        async with self._sessions() as session, session.begin():
            conversation = await repo.open_conversation(session, lead_id)
            if conversation is not None:
                await repo.add_message(
                    session,
                    conversation_id=conversation.id,
                    role="bot",
                    text=text,
                    tg_message_id=tg_message_id,
                    meta={"notice": WEB_CONFIRMATION},
                )

    # --- чтение для карточки -------------------------------------------------------------------

    async def latest(self, session: AsyncSession, lead_id: int, kind: str) -> NoticeView | None:
        notice = await session.scalar(
            select(ClientNotice)
            .where(ClientNotice.lead_id == lead_id, ClientNotice.kind == kind)
            .order_by(ClientNotice.id.desc())
            .limit(1)
        )
        return await view(session, notice) if notice is not None else None


async def view(session: AsyncSession, notice: ClientNotice) -> NoticeView:
    """Итог с учётом письма: `email_log` знает, ушло оно или нет (отправка — своей задачей)."""
    status, error, sent_at = notice.status, notice.error, notice.sent_at
    if notice.email_log_id is not None and status == "queued":
        row = await session.get(EmailLog, notice.email_log_id)
        if row is not None and row.status == "sent":
            status, sent_at = "sent", row.sent_at
        elif row is not None and row.status == "failed":
            status, error = "failed", "email_failed"
        elif row is not None and row.status == "skipped_no_smtp":
            status, error = "skipped", "smtp_not_configured"
    return NoticeView(
        id=notice.id,
        kind=notice.kind,
        channel=notice.channel,
        status=status,
        error=error,
        error_text=error_text(error),
        created_at=notice.created_at,
        sent_at=sent_at,
        detail=dict(notice.detail or {}),
    )
