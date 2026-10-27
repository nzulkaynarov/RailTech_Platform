"""Письмо «К вашему профилю привязан Telegram» (W15-H6): владелец узнаёт о привязке, даже чужой.

Колокольчика CRM у Платформы пока нет (лента — только ERP), поэтому предупреждение идёт письмом
(если коннектор «Почта» настроен) и ответом бота в самом Telegram. Без почты письма нет — не ошибка.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError
from app.repositories import users as repo
from app.services.mail import MailService
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)
TEMPLATE = "telegram_linked"


class StaffLinkNotice:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        mail: MailService,
        settings: SettingsService,
        platform_url: str | None,
    ) -> None:
        self._sessions = sessions
        self._mail = mail
        self._settings = settings
        self._platform_url = platform_url

    async def linked(self, user_id: int, username: str | None) -> None:
        try:
            await self._mail.ensure_configured()
        except ConflictError:
            logger.info("telegram_linked_notice_skipped", why="mail_not_configured")
            return
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
        if user is None or not user.is_active:
            return
        company = (await self._settings.get()).company
        profile = (
            f"{self._platform_url.rstrip('/')}/me" if self._platform_url else "Платформа → Профиль"
        )
        await self._mail.send(
            "telegram_linked",
            user.email,
            {
                "full_name": user.full_name,
                "account": f"@{username}" if username else "",
                "profile_url": profile,
                "company": company.name,
            },
            lang=user.language,
            user_id=user.id,
        )
