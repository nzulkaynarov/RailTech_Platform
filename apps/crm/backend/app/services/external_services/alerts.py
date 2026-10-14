"""Оповещения центра внешних сервисов (M3-CRM-12, ADR-0024): Telegram и почта по `service_alerts`.

Telegram: личные сообщения админам с подпиской на системные уведомления (`StaffNotifier`), канал
команды — запасной путь (`fallback`), всегда (`always`) или никогда (`never`). Почта: письмо
активным админам с e-mail и дополнительным адресам через `MailService` (шаблон `service_alert`).
Каналы прикрывают друг друга: при сбое Telegram письмо уходит, при сбое почты — сообщение.
Ошибка доставки не роняет проверку — оповещение считается отправленным, если дошло хоть куда-то.
"""

from collections.abc import Awaitable, Callable
from html import escape
from typing import Any

import structlog
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.external_incidents import AlertText
from app.models.auth import Role, User, UserRole
from app.services.mail import MailService
from app.services.settings import SettingsService
from app.services.staff_notifier import SEND_TIMEOUT_S, StaffNotifier

logger = structlog.get_logger(__name__)
BotProvider = Callable[[], Awaitable[Any]]
Paused = Callable[[str], Awaitable[bool]]


class AlertSender:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        bot: BotProvider,
        mail: MailService,
        paused: Paused,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._bot = bot
        self._mail = mail
        self._paused = paused

    async def send(self, alert: AlertText, key: str) -> bool:
        telegram = await self._telegram(alert, key)
        email = await self._email(alert, key)
        logger.info("external_alert_sent", service=key, telegram=telegram, email=email)
        return telegram or email

    async def _telegram(self, alert: AlertText, key: str) -> bool:
        cfg = await self._settings.get()
        rules = cfg.service_alerts
        bot = await self._bot()
        if bot is None:
            return False
        html = "\n".join([f"<b>{escape(alert.subject)}</b>", *(escape(x) for x in alert.lines)])
        delivered = 0
        if rules.telegram_admins:
            delivered = await StaffNotifier(self._sessions, bot).alert_admins(html, f"svc:{key}")
        channel = cfg.notifications.channel_id
        wants_channel = rules.telegram_channel == "always" or (
            rules.telegram_channel == "fallback" and delivered == 0
        )
        if wants_channel and channel is not None:
            try:
                await bot.send_message(
                    channel, html, parse_mode="HTML", request_timeout=SEND_TIMEOUT_S
                )
                delivered += 1
            except TelegramAPIError as exc:
                logger.warning("external_alert_channel_failed", service=key, error=exc.message)
        return delivered > 0

    async def _email(self, alert: AlertText, key: str) -> bool:
        cfg = await self._settings.get()
        rules = cfg.service_alerts
        if await self._paused("mail") or not await self._mail.configured():
            return False
        recipients = list(rules.extra_emails)
        if rules.email_admins:
            recipients = [*await self._admin_emails(), *recipients]
        sent = False
        for to in dict.fromkeys(recipients):
            context = {
                "subject": alert.subject,
                "body": "\n".join(alert.lines),
                "company": cfg.company.name,
            }
            try:
                await self._mail.send("service_alert", to, context)
                sent = True
            except Exception as exc:  # noqa: BLE001 — сбой письма не роняет проверку
                logger.warning("external_alert_email_failed", service=key, error=type(exc).__name__)
        return sent

    async def _admin_emails(self) -> list[str]:
        stmt = (
            select(User.email)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == "admin", User.is_active.is_(True))
            .order_by(User.id)
        )
        async with self._sessions() as session:
            return [e for e in (await session.scalars(stmt)).all() if e]
