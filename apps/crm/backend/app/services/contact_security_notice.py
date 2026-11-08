"""Уведомление безопасности контакту в Telegram по запросу ERP (FX-4).

ERP в Telegram не пишет и публикует `uz.railtech.erp.contact.security_notice_requested.v1`:
о смене банковских реквизитов компании сообщают всем администраторам и основному контакту по
всем каналам. Бот пишет на **привязанный** Telegram контакта (`telegram_identity_id`). В событии нет
реквизитов и причин. Обработчик inline: сбой сети и Telegram (5xx, лимит) поднимает исключение —
шина ответит 503 и ERP повторит доставку; отказ адресату (бот заблокирован) не повторяется.
"""

from collections.abc import Awaitable, Callable

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from rt_bus import Event
from rt_contracts.events.erp import ContactSecurityNoticeRequestedV1
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import client_texts
from app.services.contact_telegram_test import TelegramTestDelivery

logger = structlog.get_logger(__name__)

__all__ = ["SECURITY_NOTICE_REQUESTED", "SecurityNoticeDelivery"]

SECURITY_NOTICE_REQUESTED = "uz.railtech.erp.contact.security_notice_requested.v1"
SEND_TIMEOUT_S = 4


class SecurityNoticeDelivery:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        bot_provider: Callable[[], Awaitable[Bot | None]],
        *,
        dry_run: bool = False,
    ) -> None:
        self._targets = TelegramTestDelivery(sessions, bot_provider)
        self._bot_provider = bot_provider
        self._dry_run = dry_run

    async def deliver(self, event: Event) -> str:
        """`processed`, `skipped` (некому), `failed` (отказ адресату); сбой сети — исключение."""
        data = ContactSecurityNoticeRequestedV1.model_validate(event.data)
        target = await self._targets._target(data.crm_client_id, data.payload.crm_contact_id)
        if target is None:
            logger.info(
                "contact_security_notice_skipped", event_id=event.id, reason="no_linked_telegram"
            )
            return "skipped"
        tg_user_id, company = target
        bot = await self._bot_provider()
        if bot is None:
            logger.warning(
                "contact_security_notice_skipped", event_id=event.id, reason="bot_not_configured"
            )
            return "skipped"
        if self._dry_run:
            logger.info("contact_security_notice_dry_run", event_id=event.id)
            return "processed"
        language = data.payload.language.value if data.payload.language else None
        text = client_texts.contact_security_notice(language, data.payload.kind.value, company)
        try:
            await bot.send_message(chat_id=tg_user_id, text=text, request_timeout=SEND_TIMEOUT_S)
        except (
            TelegramNetworkError,
            TelegramRetryAfter,
            TelegramServerError,
            OSError,
            TimeoutError,
        ):
            logger.warning("contact_security_notice_retry", event_id=event.id)
            raise
        except TelegramAPIError as exc:
            logger.warning(
                "contact_security_notice_failed", event_id=event.id, error=type(exc).__name__
            )
            return "failed"
        logger.info("contact_security_notice_sent", event_id=event.id)
        return "processed"
