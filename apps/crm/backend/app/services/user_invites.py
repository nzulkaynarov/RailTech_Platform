"""Письма сотруднику (M3-CRM-08, ДВ-7): «Пригласить» и «Сбросить пароль по почте».

В письме нет пароля: только одноразовая ссылка на страницу «Задайте пароль» Платформы (та же, что у
«Забыли пароль?»): токен хранится хешем, живёт 72 часа (приглашение) или час (сброс) и гасится при
использовании. Прежний пароль и сессии сотрудника перестают действовать сразу, статус —
«Приглашён», пока он не задаст новый. Проверка коннектора идёт до любых изменений: без SMTP пароль
остаётся прежним, а админ получает 409 `smtp_not_configured` и может выдать временный пароль на
экране, без почты. Ссылка ведёт на адрес Платформы (`PLATFORM_PUBLIC_URL` / `PLATFORM_DOMAIN`);
адреса нет — 409 (W15-H8a). Ссылок на одну учётную запись — не больше 3 в час, как у
«Забыли пароль?»: иначе 429.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import password_reset as rules
from app.domain.errors import ConflictError, NotFoundError, RateLimitedError, Reason
from app.models.auth import PasswordResetToken, User
from app.repositories import users as repo
from app.security import audit
from app.security.audit import Actor
from app.security.passwords import hash_password, temporary_password
from app.services.mail import EmailLogView, MailService
from app.services.settings import SettingsService
from app.services.users import close_sessions

logger = structlog.get_logger(__name__)

INVITE: Final = "invite"
PASSWORD_RESET: Final = "password_reset"  # noqa: S105 — имя шаблона письма, не секрет
PLATFORM_URL_MISSING: Final = (
    "Приглашение не отправлено: не задан адрес Платформы для ссылки входа. "
    "Его задаёт тот, кто разворачивал Платформу (хостинг)."
)
PLATFORM_URL_HINT: Final = "Задайте PLATFORM_DOMAIN (или PLATFORM_PUBLIC_URL) в .env сервера"
_AUDIT: Final = {INVITE: "user.invite", PASSWORD_RESET: "user.reset_password_email"}
_TTL: Final = {INVITE: rules.INVITE_TTL, PASSWORD_RESET: rules.TOKEN_TTL}


class UserInviteService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        mail: MailService,
        settings: SettingsService,
        platform_url: str | None = None,
    ) -> None:
        self._sessions = sessions
        self._mail = mail
        self._settings = settings
        self._platform_url = platform_url

    async def invite(self, actor: Actor, user_id: int) -> EmailLogView:
        return await self._send_link(actor, user_id, INVITE)

    async def reset_password_email(self, actor: Actor, user_id: int) -> EmailLogView:
        return await self._send_link(actor, user_id, PASSWORD_RESET)

    async def _send_link(self, actor: Actor, user_id: int, template: str) -> EmailLogView:
        await self._mail.ensure_configured()
        platform_url = self._platform_url
        if not platform_url:
            logger.warning("platform_url_missing", hint=PLATFORM_URL_HINT)
            raise ConflictError(PLATFORM_URL_MISSING, hint=PLATFORM_URL_HINT)
        now = datetime.now(UTC)
        token = rules.new_token()
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            await _check_rate(session, user_id, now)
            _lock_out(user)
            await _issue_token(session, user_id, token, now + _TTL[template], now)
            await close_sessions(session, user_id)
            email, full_name, language = user.email, user.full_name, user.language
            await audit.record(session, actor, _AUDIT[template], "user", user_id)
        company = (await self._settings.get()).company
        view = await self._mail.send(
            template,
            email,
            {
                "full_name": full_name,
                "email": email,
                "set_password_url": rules.reset_link(platform_url, token),
                "company": company.name,
            },
            lang=language,
            user_id=user_id,
            requested_by=actor.user_id,
        )
        logger.info("user_email_queued", template=template, user_id=user_id, email_log_id=view.id)
        return view


async def _check_rate(session: AsyncSession, user_id: int, now: datetime) -> None:
    recent = await session.scalar(
        select(func.count())
        .select_from(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.created_at >= now - rules.WINDOW,
        )
    )
    if rules.rate_exceeded(recent or 0):
        raise RateLimitedError(
            "too many set-password links for this employee",
            reason=Reason.RATE_LIMITED,
            retry_after_s=int(timedelta(hours=1).total_seconds()),
        )


async def _issue_token(
    session: AsyncSession, user_id: int, token: str, expires_at: datetime, now: datetime
) -> None:
    """Новая ссылка отменяет прежние неиспользованные: действует всегда только последняя."""
    await session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    session.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=rules.hash_token(token),
            channel="email",
            expires_at=expires_at,
            created_at=now,
        )
    )


def _lock_out(user: User) -> None:
    """Прежний пароль закрыт; нового никто не знает, пока сотрудник сам его не задаст."""
    user.password_hash = hash_password(temporary_password())
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
