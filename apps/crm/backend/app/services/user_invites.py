"""Письма сотруднику (M3-CRM-08): «Пригласить» и «Сбросить пароль по почте».

Оба сценария — новый временный пароль (как у ручного сброса, Q-010) и письмо через коннектор
«Почта». Проверка коннектора идёт до смены пароля: без SMTP сотрудник не остаётся с неизвестным
паролем, а админ получает 409 `smtp_not_configured` и может выдать пароль вручную, как раньше.
Ссылка «Вход» в письме — адрес Платформы (`PLATFORM_PUBLIC_URL` / `PLATFORM_DOMAIN`) + `/login`;
адреса нет — 409 до смены пароля, а не письмо со ссылкой на localhost (W15-H8a).
"""

from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, NotFoundError
from app.models.auth import User
from app.repositories import users as repo
from app.security import audit
from app.security.audit import Actor
from app.security.passwords import hash_password, temporary_password
from app.services.mail import EmailLogView, MailService
from app.services.settings import SettingsService
from app.services.users import revoke_tokens

logger = structlog.get_logger(__name__)

INVITE: Final = "invite"
PASSWORD_RESET: Final = "password_reset"  # noqa: S105 — имя шаблона письма, не секрет
PLATFORM_URL_MISSING: Final = (
    "Адрес Платформы не задан, поэтому письмо со ссылкой для входа не отправлено, "
    "а пароль не менялся. Адрес задаётся при развёртывании (PLATFORM_DOMAIN в .env сервера)."
)
_AUDIT: Final = {INVITE: "user.invite", PASSWORD_RESET: "user.reset_password_email"}


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
        return await self._send_temporary_password(actor, user_id, INVITE)

    async def reset_password_email(self, actor: Actor, user_id: int) -> EmailLogView:
        return await self._send_temporary_password(actor, user_id, PASSWORD_RESET)

    async def _send_temporary_password(
        self, actor: Actor, user_id: int, template: str
    ) -> EmailLogView:
        await self._mail.ensure_configured()
        platform_url = self._platform_url
        if not platform_url:
            raise ConflictError(PLATFORM_URL_MISSING)
        password = temporary_password()
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            _rotate(user, password)
            await revoke_tokens(session, user_id)
            email, full_name = user.email, user.full_name
            await audit.record(session, actor, _AUDIT[template], "user", user_id)
        company = (await self._settings.get()).company
        view = await self._mail.send(
            template,
            email,
            {
                "full_name": full_name,
                "email": email,
                "temporary_password": password,
                "platform_url": platform_url,
                "company": company.name,
            },
            user_id=user_id,
            requested_by=actor.user_id,
        )
        logger.info("user_email_queued", template=template, user_id=user_id, email_log_id=view.id)
        return view


def _rotate(user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
