"""Доставка кода акцепта КП контакту в Telegram (шов 0.3.0, Q-FIX22-1, B4).

Событие `uz.railtech.erp.quote.acceptance_code_requested.v1`.

Код — секрет: он живёт только в памяти запроса приёмника шины и в сообщении бота. Шина хранит в
inbox маску вместо кода (`BusConfig.secret_fields`), очередь не используется (задача Procrastinate
хранила бы аргументы в БД), в ленту лида и в логи код не попадает. Обработчик inline: ошибка
доставки не откатывает приём и не просит издателя повторить — код живёт минуты, повтор события не
вернёт его (клиент запросит новый код в кабинете); недоставленное пишется в лог (причина без кода).
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus.erp_event import ErpEvent
from app.config import Settings
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.services.erp_bot_messages import acceptance_code_message, pick_language
from app.services.erp_event_handlers import aware
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

Outcome = Literal["delivered", "skipped", "failed"]
# Меньше таймаута доставки вебхука у ERP (10 с): медленный Telegram не должен вызвать её повтор.
SEND_TIMEOUT_S = 4


class AcceptanceCodeDelivery:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings_service: SettingsService,
        bot_provider: Callable[[], Awaitable[Bot | None]],
        config: Settings,
    ) -> None:
        self._sessions = sessions
        self._settings_service = settings_service
        self._bot_provider = bot_provider
        self._config = config

    async def deliver(self, event_id: str, event: ErpEvent) -> str:
        """Отправить код; вернуть исход: `processed`, `skipped` или `failed`.

        Исключения не пробрасываются: ответ ERP при любом исходе — 200 (ретрай бесполезен).
        """
        try:
            outcome, error = await self._send(event)
        except (TelegramAPIError, OSError, ValueError) as exc:
            # Только класс исключения: текст ошибки Telegram не должен тащить в лог лишнего.
            outcome, error = "failed", f"telegram: {type(exc).__name__}"
        except Exception as exc:
            logger.exception("erp_acceptance_code_failed", event_id=event_id)
            outcome, error = "failed", f"unexpected: {type(exc).__name__}"
        if outcome == "delivered":
            logger.info("erp_acceptance_code_sent", event_id=event_id)
            return "processed"
        logger.warning("erp_acceptance_code_not_sent", event_id=event_id, reason=error)
        return "skipped" if outcome == "skipped" else "failed"

    async def _send(self, event: ErpEvent) -> tuple[Outcome, str | None]:
        payload = event.payload
        remaining = (aware(payload.expires_at) - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            return "skipped", "code already expired"
        async with self._sessions() as session:
            client = await session.get(Client, event.crm_client_id)
            if client is None:
                return "failed", f"Client #{event.crm_client_id} not found"
            if client.erp_company_id not in (None, event.erp_company_id):
                return "failed", "company mismatch"
            contact = await session.get(ClientContact, payload.crm_contact_id)
            if contact is None or contact.client_id != client.id:
                return "failed", f"Contact #{payload.crm_contact_id} not found"
            tg_user_id = await contact_telegram(session, client, contact)
            if tg_user_id is None:
                return "failed", "contact has no telegram"
            lead = await session.scalar(
                select(Lead).where(Lead.client_id == client.id).order_by(Lead.id.desc()).limit(1)
            )
        bot = await self._bot_provider()
        if bot is None:
            return "failed", "bot is not running"
        if self._config.telegram_dry_run:
            return "skipped", "telegram dry run"
        message = acceptance_code_message(
            code=payload.code,
            minutes=max(1, round(remaining / 60)),
            deal_title=(event.deal.title if event.deal else "—"),
            texts=(await self._settings_service.get()).texts,
            language=pick_language(lead.language if lead else None),
        )
        await bot.send_message(
            chat_id=tg_user_id, text=message.text, request_timeout=SEND_TIMEOUT_S
        )
        return "delivered", None


async def contact_telegram(
    session: AsyncSession, client: Client, contact: ClientContact
) -> int | None:
    """Telegram контакта: его собственная привязка; у основного контакта — ещё и клиента (как при
    передаче в ERP, `erp_handoff._telegram_of`). Заблокировавший бота аккаунт не подходит.
    """
    conditions: list[ColumnElement[bool]] = [TelegramIdentity.is_blocked.is_(False)]
    if contact.telegram_identity_id is not None:
        conditions.append(TelegramIdentity.id == contact.telegram_identity_id)
    elif contact.is_primary:
        conditions.append(TelegramIdentity.client_id == client.id)
    else:
        return None
    return await session.scalar(
        select(TelegramIdentity.tg_user_id)
        .where(*conditions)
        .order_by(TelegramIdentity.id)
        .limit(1)
    )
