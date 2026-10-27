"""`/start staff_<код>`: сотрудник привязывает Telegram из профиля Платформы (W15-H6).

Клиентский бот один, поэтому команда сотрудника отличается префиксом аргумента `staff_`: любой
другой `/start` (без аргумента, клиентские deep-link'и) этот роутер пропускает: дальше обычный
путь клиента (`handlers.on_start`). Роутер подключается раньше клиентских.
"""

from typing import Any

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from app.domain import staff_telegram as rules
from app.services.staff_telegram_link import StaffTelegramLinkService

router = Router(name="staff-link")
router.message.filter(F.chat.type == "private")


def _is_staff_start(
    message: Message, command: CommandObject, staff_link: StaffTelegramLinkService | None = None
) -> dict[str, Any] | bool:
    """Только `/start staff_<16 символов>` при подключённом сервисе привязки."""
    if staff_link is None:
        return False
    code = rules.staff_code_of(command.args)
    return {"staff_code": code} if code else False


@router.message(CommandStart(deep_link=True), _is_staff_start, F.from_user)
async def on_staff_start(
    message: Message, staff_code: str, staff_link: StaffTelegramLinkService
) -> None:
    sender = message.from_user
    if sender is None:  # отфильтровано F.from_user, проверка для типов
        return
    outcome = await staff_link.confirm(staff_code, sender.id, sender.username)
    language = outcome.language or (sender.language_code or "")[:2] or None
    table = {"linked": rules.LINKED, "taken": rules.TAKEN}.get(outcome.status, rules.INVALID)
    await message.answer(rules.text(table, language))
