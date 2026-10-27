"""«Забыли пароль?» (W15-H6): ссылка сброса на почту или в Telegram, затем новый пароль.

`request` ничего не сообщает о существовании учётной записи: для чужого адреса, отключённого
сотрудника, превышенного лимита и отсутствия канала он отрабатывает одинаково тихо (в журнале —
причина без адреса). Ссылка ведёт на Платформу (`PLATFORM_PUBLIC_URL`), токен одноразовый и
хранится хешем. Почта главнее; если письмо не ушло, пробуем Telegram. Нет ни того, ни другого —
ссылка не создаётся, сотрудник идёт к администратору (экран говорит об этом заранее).
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import password_reset as rules
from app.domain.errors import ConflictError, Reason, ValidationFailedError
from app.models.auth import PasswordResetToken, User
from app.repositories import users as repo
from app.security import audit
from app.security.audit import Actor
from app.security.passwords import WeakPasswordError, hash_password, validate_new_password
from app.services.mail import MailService
from app.services.settings import SettingsService
from app.services.users import revoke_tokens

logger = structlog.get_logger(__name__)
TEMPLATE = "password_reset_link"
SEND_TIMEOUT_S = 10


class Sender(Protocol):
    async def send_message(
        self, chat_id: int, text: str, *, request_timeout: int | None = ...
    ) -> Any: ...


BotProvider = Callable[[], Awaitable[Sender | None]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PasswordResetService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        mail: MailService,
        settings: SettingsService,
        bot: BotProvider,
        platform_url: str | None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sessions = sessions
        self._mail = mail
        self._settings = settings
        self._bot = bot
        self._platform_url = platform_url
        self._clock = clock

    async def request(self, identifier: str) -> None:
        """Выпустить ссылку и отправить; наружу — ничего (ответ API одинаков для любого ввода).

        Вызывается после ответа клиенту: сбой пишется в журнал и не доходит до сотрудника."""
        try:
            await self._request(identifier)
        except Exception:
            logger.error("password_reset_failed", exc_info=True)

    async def _request(self, identifier: str) -> None:
        if not self._platform_url:
            logger.warning("password_reset_skipped", why="platform_url_missing")
            return
        email = identifier.strip().lower()
        now = self._clock()
        bot = await self._bot()
        mail_ready = await self._mail_ready()
        token = rules.new_token()
        async with self._sessions() as session, session.begin():
            user = await repo.by_email(session, email, for_update=True)
            if user is None or not user.is_active:
                logger.info("password_reset_skipped", why="no_active_user")
                return
            recent = await session.scalar(
                select(func.count())
                .select_from(PasswordResetToken)
                .where(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.created_at >= now - rules.WINDOW,
                )
            )
            if rules.rate_exceeded(recent or 0):
                logger.info("password_reset_skipped", why="rate_limited", user_id=user.id)
                return
            telegram_ready = user.tg_user_id is not None and bot is not None
            channel = rules.delivery_channel(mail_ready=mail_ready, telegram_ready=telegram_ready)
            if channel is None:
                logger.info("password_reset_skipped", why="no_channel", user_id=user.id)
                return
            row = PasswordResetToken(
                user_id=user.id,
                token_hash=rules.hash_token(token),
                channel=channel,
                expires_at=now + rules.TOKEN_TTL,
                created_at=now,
            )
            session.add(row)
            snapshot = (user.id, user.email, user.full_name, user.language, user.tg_user_id)
        user_id, to, name, language, tg_user_id = snapshot
        link = rules.reset_link(self._platform_url, token)
        delivered = False
        if channel == "email":
            delivered = await self._send_mail(user_id, to, name, language, link)
            if not delivered and tg_user_id is not None and bot is not None:
                delivered = await self._send_telegram(bot, tg_user_id, language, link)
                channel = "telegram"
        else:
            delivered = (
                bot is not None
                and tg_user_id is not None
                and await self._send_telegram(bot, tg_user_id, language, link)
            )
        if not delivered:
            await self._discard(token)
            return
        await self._mark_channel(token, channel)
        logger.info("password_reset_sent", user_id=user_id, channel=channel)

    async def _mail_ready(self) -> bool:
        try:
            await self._mail.ensure_configured()
        except ConflictError:
            return False
        return True

    async def _send_mail(self, user_id: int, to: str, name: str, language: str, link: str) -> bool:
        company = (await self._settings.get()).company
        try:
            await self._mail.send(
                "password_reset_link",
                to,
                {"full_name": name, "reset_url": link, "company": company.name},
                lang=language,
                user_id=user_id,
            )
        except Exception as exc:  # noqa: BLE001 — доставка best-effort, пробуем запасной канал
            logger.warning("password_reset_mail_failed", user_id=user_id, error=type(exc).__name__)
            return False
        return True

    async def _send_telegram(self, bot: Sender, tg_user_id: int, language: str, link: str) -> bool:
        try:
            await bot.send_message(
                tg_user_id, rules.telegram_text(language, link), request_timeout=SEND_TIMEOUT_S
            )
        except Exception as exc:  # noqa: BLE001 — доставка best-effort, ответ запроса одинаков
            logger.warning("password_reset_telegram_failed", error=type(exc).__name__)
            return False
        return True

    async def _discard(self, token: str) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(PasswordResetToken).where(
                    PasswordResetToken.token_hash == rules.hash_token(token)
                )
            )
            if row is not None:
                await session.delete(row)

    async def _mark_channel(self, token: str, channel: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(PasswordResetToken)
                .where(PasswordResetToken.token_hash == rules.hash_token(token))
                .values(channel=channel)
            )

    async def reset(self, token: str, new_password: str) -> None:
        """Новый пароль по ссылке: токен гасится, прочие ссылки и сессии сотрудника — тоже."""
        now = self._clock()
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(PasswordResetToken)
                .where(PasswordResetToken.token_hash == rules.hash_token(token))
                .with_for_update()
            )
            user = await repo.get(session, row.user_id, for_update=True) if row else None
            if (
                row is None
                or user is None
                or not user.is_active
                or not rules.usable(row.expires_at, row.used_at, now)
            ):
                raise ValidationFailedError(
                    "the reset link is invalid or has expired",
                    reason=Reason.RESET_TOKEN_INVALID,
                    field="token",
                )
            try:
                validate_new_password(new_password, email=user.email)
            except WeakPasswordError as exc:
                raise ValidationFailedError(
                    str(exc), reason=Reason.WEAK_PASSWORD, field="new_password"
                ) from exc
            _set_password(user, new_password)
            await session.execute(
                update(PasswordResetToken)
                .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
                .values(used_at=now)
            )
            await revoke_tokens(session, user.id)
            await audit.record(
                session, Actor(user.id, "user"), "user.password_reset_link", "user", user.id
            )


def _set_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.must_change_password = False
    user.failed_logins = 0
    user.locked_until = None
