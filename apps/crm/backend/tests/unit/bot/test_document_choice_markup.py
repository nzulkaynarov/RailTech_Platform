"""BOT-07 в боте: кнопки выбора документа и отказ на чужой id в callback (подставной Bot)."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from app.bot import keyboards
from app.bot.client_handlers import on_document
from app.bot.handlers import send
from app.schemas.settings import AppSettings
from app.services.client_bot import ChatStatus
from app.services.conversation_types import Outgoing

CFG = AppSettings()
USER = 42


class Settings:
    async def get(self) -> AppSettings:
        return CFG


class OwnDocs:
    """Клиент видит только документ 7 (как `get_for_client` по подтверждённой привязке)."""

    def __init__(self) -> None:
        self.asked: list[int] = []

    async def document(self, tg_user_id: int, document_id: int) -> Outgoing | None:
        self.asked.append(document_id)
        return Outgoing("Отправляю", document={"url": "u"}) if document_id == 7 else None

    async def status(self, tg_user_id: int) -> ChatStatus:
        return ChatStatus("client", "ru", 1, 5, False)


async def test_choices_are_sent_as_document_buttons() -> None:
    bot = AsyncMock()
    item = Outgoing("Выберите:", choices=[(7, "Счёт · 2026-09-01"), (9, "Счёт · 2026-10-01")])
    await send(bot, USER, [item], Settings())  # type: ignore[arg-type]
    markup = bot.send_message.await_args.kwargs["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    data = [row[0].callback_data for row in markup.inline_keyboard]
    assert data == [f"{keyboards.DOC_PREFIX}7", f"{keyboards.DOC_PREFIX}9"]


def _tap(bot: AsyncMock, data: str) -> CallbackQuery:
    raw: dict[str, Any] = {
        "id": "1",
        "from": {"id": USER, "is_bot": False, "first_name": "Азиз"},
        "chat_instance": "c",
        "data": data,
        "message": {
            "message_id": 3,
            "date": datetime(2026, 10, 12, tzinfo=UTC),
            "chat": {"id": USER, "type": "private"},
            "text": "Выберите:",
        },
    }
    return CallbackQuery.model_validate(raw).as_(bot)


async def test_foreign_document_id_in_callback_is_refused() -> None:
    bot, docs = AsyncMock(), OwnDocs()
    await on_document(_tap(bot, f"{keyboards.DOC_PREFIX}9"), bot, docs, Settings())
    assert docs.asked == [9]
    bot.send_message.assert_awaited_once_with(USER, CFG.texts.document_failed.ru)
