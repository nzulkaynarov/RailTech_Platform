"""Приглашение контакта в кабинет через Telegram: доставка по событию ERP `invite.requested` (D1-9,
Q-FIX23-1).

Событие `uz.railtech.erp.invite.requested.v1`. ERP в Telegram не пишет — она публикует событие, бот
CRM присылает
контакту сообщение с кнопкой «Открыть кабинет» (Mini App: вход по Telegram-аккаунту контакта, ссылок
и токенов в событии
нет, поэтому оно не секретно и лежит в inbox как обычное). Обработчик inline, как у кода акцепта:
ошибка доставки не
откатывает приём и не просит издателя повторить; итог — отметка в `client_notices`
(`PortalInviteService.resolve_telegram`),
которую менеджер видит в карточке клиента вместе с причиной и действием «Отправить повторно другим
каналом».
"""

from collections.abc import Awaitable, Callable

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus.erp_event import ErpEvent
from app.config import Settings
from app.domain import client_texts
from app.models.clients import Client, ClientContact
from app.models.leads import Lead
from app.services.portal_invites import PortalInviteService, telegram_of_contact
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

# Меньше таймаута доставки у ERP (10 с): медленный Telegram не должен вызвать её повтор.
SEND_TIMEOUT_S = 4


class InviteDelivery:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings_service: SettingsService,
        bot_provider: Callable[[], Awaitable[Bot | None]],
        config: Settings,
        invites: PortalInviteService,
    ) -> None:
        self._sessions = sessions
        self._settings_service = settings_service
        self._bot_provider = bot_provider
        self._config = config
        self._invites = invites

    async def deliver(self, event_id: str, event: ErpEvent) -> str:
        """Отправить приглашение; исход — `processed` или `failed`. Исключения не пробрасываются."""
        client_id, contact_id = event.crm_client_id, int(event.payload.crm_contact_id)
        try:
            error = await self._send(event, client_id, contact_id)
        except TelegramForbiddenError:
            error = "telegram_blocked"
        except (TelegramAPIError, OSError, TimeoutError, ValueError) as exc:
            logger.warning(
                "erp_invite_telegram_failed", event_id=event_id, error=type(exc).__name__
            )
            error = "telegram_failed"
        except Exception:
            logger.exception("erp_invite_unexpected", event_id=event_id)
            error = "telegram_failed"
        try:
            await self._invites.resolve_telegram(client_id, contact_id, error)
        except Exception:
            logger.exception("erp_invite_state_not_saved", event_id=event_id)
        if error is None:
            logger.info("erp_invite_sent", event_id=event_id, client_id=client_id)
            return "processed"
        logger.warning("erp_invite_not_sent", event_id=event_id, client_id=client_id, reason=error)
        return "failed"

    async def _send(self, event: ErpEvent, client_id: int, contact_id: int) -> str | None:
        """Код причины или `None`, если сообщение ушло."""
        async with self._sessions() as session:
            client = await session.get(Client, client_id)
            contact = await session.get(ClientContact, contact_id)
            if client is None or contact is None or contact.client_id != client.id:
                return "no_telegram"
            tg_user_id = await telegram_of_contact(session, client, contact)
            lead = await session.scalar(
                select(Lead).where(Lead.client_id == client.id).order_by(Lead.id.desc()).limit(1)
            )
            name = contact.full_name
            language = lead.language if lead is not None else str(event.payload.language or "ru")
        if tg_user_id is None:
            return "no_telegram"
        cfg = await self._settings_service.get()
        if not cfg.company.cabinet_url:
            return "cabinet_not_configured"
        bot = await self._bot_provider()
        if bot is None:
            return "bot_not_configured"
        if self._config.telegram_dry_run:
            logger.info("erp_invite_dry_run", client_id=client_id)
            return None
        url = cfg.company.cabinet_url
        label = client_texts.open_cabinet_label(language)
        # Mini App открывается только по https; на стенде с http — обычная ссылка.
        button = (
            InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))
            if url.startswith("https://")
            else InlineKeyboardButton(text=label, url=url)
        )
        await bot.send_message(
            chat_id=tg_user_id,
            text=client_texts.invite_bot(language, name, cfg.company.name),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]),
            request_timeout=SEND_TIMEOUT_S,
        )
        return None
