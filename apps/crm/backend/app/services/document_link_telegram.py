"""Код и личная ссылка документа в Telegram получателя по запросу ERP (ДК-4, ADR-0030).

ERP в Telegram не пишет и публикует `uz.railtech.erp.document_link.telegram_requested.v1`:
получатель личной ссылки на КП, договор, счёт или акт, если у него привязан Telegram, получает
в бот то же, что и на почту. Бот пишет на **привязанный** Telegram именно этого контакта
(`client_contacts.telegram_identity_id`), а не на любой Telegram клиента.

* `kind=code` — шесть цифр входа по ссылке и срок; в сообщении нет ни вида, ни номера,
  ни продавца документа;
* `kind=link` — одна короткая строка (вид, номер, продавец) и кнопка со ссылкой.

Код и ссылка — секреты: в inbox шины — маска, полное событие получает только этот
inline-обработчик; ни код, ни ссылка не попадают в лог и в текст ошибки (разбор события не
пробрасывает текст pydantic — он цитирует входные значения). Сбой сети и Telegram (5xx, лимит)
поднимает исключение — шина ответит 503 и ERP повторит доставку, пока значение секрета живо
в её кэше; отказ адресату (бот заблокирован) не повторяется.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pydantic import ValidationError
from rt_bus import Event
from rt_contracts.events.erp import DocumentLinkTelegramRequestedV1
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import client_texts
from app.domain.urls import is_http_url
from app.services.contact_telegram_test import TelegramTestDelivery

logger = structlog.get_logger(__name__)

__all__ = ["DOCUMENT_LINK_REQUESTED", "DocumentLinkTelegramDelivery"]

DOCUMENT_LINK_REQUESTED = "uz.railtech.erp.document_link.telegram_requested.v1"
# Меньше таймаута доставки у ERP (10 с): медленный Telegram не вызывает её повтор.
SEND_TIMEOUT_S = 4


class DocumentLinkTelegramDelivery:
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
        """`processed`, `skipped` (нечего слать), `failed` (отказ); сбой сети — исключение."""
        try:
            data = DocumentLinkTelegramRequestedV1.model_validate(event.data)
        except ValidationError:
            # Текст ошибки несёт входные значения (в них код и ссылка): наружу — только факт.
            raise ValueError("invalid document link telegram event") from None
        payload = data.payload
        language = payload.language.value if payload.language else None
        text, markup = self._message(event.id, data, language)
        if text is None:
            return "skipped"
        target = await self._targets._target(data.crm_client_id, payload.crm_contact_id)
        if target is None:
            logger.info(
                "document_link_telegram_skipped", event_id=event.id, reason="no_linked_telegram"
            )
            return "skipped"
        tg_user_id, _company = target
        bot = await self._bot_provider()
        if bot is None:
            logger.warning(
                "document_link_telegram_skipped", event_id=event.id, reason="bot_not_configured"
            )
            return "skipped"
        if self._dry_run:
            logger.info("document_link_telegram_dry_run", event_id=event.id)
            return "processed"
        try:
            await bot.send_message(
                chat_id=tg_user_id, text=text, reply_markup=markup, request_timeout=SEND_TIMEOUT_S
            )
        except (
            TelegramNetworkError,
            TelegramRetryAfter,
            TelegramServerError,
            OSError,
            TimeoutError,
        ) as exc:
            logger.warning("document_link_telegram_retry", event_id=event.id)
            # Текст исключения Telegram мог процитировать сообщение (код, ссылку), а шина логирует
            # его целиком: наружу — только класс.
            raise RuntimeError(f"telegram delivery failed: {type(exc).__name__}") from None
        except TelegramAPIError as exc:
            logger.warning(
                "document_link_telegram_failed", event_id=event.id, error=type(exc).__name__
            )
            return "failed"
        logger.info("document_link_telegram_sent", event_id=event.id, kind=payload.kind.value)
        return "processed"

    @staticmethod
    def _message(
        event_id: str, data: DocumentLinkTelegramRequestedV1, language: str | None
    ) -> tuple[str | None, InlineKeyboardMarkup | None]:
        payload = data.payload
        if payload.kind.value == "code":
            if not payload.code or payload.expires_at is None:
                logger.warning(
                    "document_link_telegram_skipped", event_id=event_id, reason="no_code"
                )
                return None, None
            remaining = (payload.expires_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                logger.info("document_link_telegram_skipped", event_id=event_id, reason="expired")
                return None, None
            minutes = max(1, round(remaining / 60))
            return client_texts.document_link_code(language, payload.code, minutes), None
        if not payload.url or not is_http_url(payload.url):
            logger.warning("document_link_telegram_skipped", event_id=event_id, reason="no_url")
            return None, None
        text = client_texts.document_link_message(
            language, payload.document_kind.value, payload.number, payload.seller_name
        )
        button = InlineKeyboardButton(
            text=client_texts.document_link_button(language), url=payload.url
        )
        return text, InlineKeyboardMarkup(inline_keyboard=[[button]])
