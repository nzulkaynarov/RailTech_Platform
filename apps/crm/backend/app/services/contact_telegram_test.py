"""Проверочное сообщение контакту в Telegram по запросу ERP (NOTIFY-1, ADR-0023 п. 3).

Контакт в кабинете (Профиль → «Уведомления») нажал «Отправить проверочное сообщение»; ERP в
Telegram не пишет и публикует `uz.railtech.erp.contact.telegram_test_requested.v1` (прореживание —
у ERP, раз в минуту на контакт). Бот пишет короткое сообщение на языке контакта на **его**
привязанный Telegram (`client_contacts.telegram_identity_id`), а не на любой Telegram клиента:
проверяется именно то, что привязал человек. Обработчик inline, как у приглашения: сбой Telegram не
откатывает приём и не просит ERP повторить — запрос пользователя разовый, повторит он сам.
"""

from collections.abc import Awaitable, Callable

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from rt_bus import Event
from rt_contracts.events.erp import ContactTelegramTestRequestedV1
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import client_texts
from app.models.clients import Client, ClientContact
from app.models.leads import TelegramIdentity

logger = structlog.get_logger(__name__)

__all__ = ["TEST_REQUESTED", "TelegramTestDelivery"]

TEST_REQUESTED = "uz.railtech.erp.contact.telegram_test_requested.v1"
# Меньше таймаута доставки у ERP (10 с): медленный Telegram не должен вызвать её повтор.
SEND_TIMEOUT_S = 4


class TelegramTestDelivery:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        bot_provider: Callable[[], Awaitable[Bot | None]],
        *,
        dry_run: bool = False,
    ) -> None:
        self._sessions = sessions
        self._bot_provider = bot_provider
        self._dry_run = dry_run

    async def deliver(self, event: Event) -> str:
        """`processed` — ушло (или dry-run), `skipped` — некому или нечем, `failed` — отказ."""
        data = ContactTelegramTestRequestedV1.model_validate(event.data)
        target = await self._target(data.crm_client_id, data.payload.crm_contact_id)
        if target is None:
            logger.info(
                "contact_telegram_test_skipped", event_id=event.id, reason="no_linked_telegram"
            )
            return "skipped"
        tg_user_id, company = target
        bot = await self._bot_provider()
        if bot is None:
            logger.warning(
                "contact_telegram_test_skipped", event_id=event.id, reason="bot_not_configured"
            )
            return "skipped"
        language = data.payload.language.value if data.payload.language else None
        if self._dry_run:
            logger.info("contact_telegram_test_dry_run", event_id=event.id)
            return "processed"
        try:
            await bot.send_message(
                chat_id=tg_user_id,
                text=client_texts.contact_link_test(language, company),
                request_timeout=SEND_TIMEOUT_S,
            )
        except (TelegramAPIError, OSError, TimeoutError) as exc:
            logger.warning(
                "contact_telegram_test_failed", event_id=event.id, error=type(exc).__name__
            )
            return "failed"
        logger.info("contact_telegram_test_sent", event_id=event.id)
        return "processed"

    async def _target(self, client_id: int, contact_id: int) -> tuple[int, str] | None:
        """Telegram контакта и название компании; контакт другого клиента, без привязки или
        заблокировавший бота — `None`."""
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(TelegramIdentity.tg_user_id, Client.name)
                    .join(ClientContact, ClientContact.telegram_identity_id == TelegramIdentity.id)
                    .join(Client, Client.id == ClientContact.client_id)
                    .where(
                        ClientContact.id == contact_id,
                        ClientContact.client_id == client_id,
                        TelegramIdentity.is_blocked.is_(False),
                    )
                )
            ).first()
        return (int(row[0]), str(row[1])) if row is not None else None
