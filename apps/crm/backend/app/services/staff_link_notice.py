"""Письмо «К вашему профилю привязан Telegram» (W15-H6): владелец узнаёт о привязке, даже чужой.

Предупреждение идёт в колокольчик Платформы (`staff_notifications`, W15-H7), письмом (если
коннектор «Почта» настроен) и ответом бота в самом Telegram. Без почты письма нет — не ошибка.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError
from app.repositories import users as repo
from app.services.mail import MailService
from app.services.settings import SettingsService
from app.services.staff_notifications import StaffNotificationService

logger = structlog.get_logger(__name__)
TEMPLATE = "telegram_linked"


class StaffLinkNotice:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        mail: MailService,
        settings: SettingsService,
        platform_url: str | None,
        notifications: StaffNotificationService | None = None,
    ) -> None:
        self._sessions = sessions
        self._mail = mail
        self._settings = settings
        self._platform_url = platform_url
        self._notifications = notifications

    async def linked(self, user_id: int, username: str | None) -> None:
        try:
            await self._bell(user_id, username)
        except Exception:
            # Колокольчик — дополнение: письмо с предупреждением уходит в любом случае.
            logger.exception("telegram_linked_bell_failed", user_id=user_id)
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

    async def _bell(self, user_id: int, username: str | None) -> None:
        """Строка в колокольчике: вкладка «Система», без объекта (отвязать можно в профиле)."""
        if self._notifications is None:
            return
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
        if user is None or not user.is_active:
            return
        title, subtitle = _BELL.get(user.language, _BELL["ru"])
        account = f" @{username}" if username else ""
        await self._notifications.add(
            [user_id],
            kind="telegram_linked",
            tab="system",
            title=f"{title}{account}",
            subtitle=subtitle,
        )


_BELL = {
    "ru": ("К вашему профилю привязан Telegram", "Если это не вы — отвяжите его в профиле."),
    "uz": ("Profilingizga Telegram ulandi", "Agar bu siz bo‘lmasangiz — profilda uzib qo‘ying."),
    "en": ("Telegram is linked to your profile", "If this was not you, unlink it in your profile."),
}
