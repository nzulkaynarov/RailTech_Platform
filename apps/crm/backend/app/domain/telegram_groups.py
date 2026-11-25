"""Группа с секретарём (ADR-0032): код привязки, состояние доступа и тексты бота. Чистые функции."""

import secrets
from datetime import datetime, timedelta
from typing import Final, Literal

CODE_TTL: Final = timedelta(hours=48)
# Без 0/O/1/I/L: код читают с экрана и вводят руками.
_ALPHABET: Final = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH: Final = 6
DEFAULT_LANGUAGE: Final = "ru"
GROUP_CHAT_TYPES: Final = frozenset({"group", "supergroup"})
# Бот скачивает файл только до этого размера (Bot API); больше — пометка со ссылкой на группу.
NOTE_TOO_LARGE: Final = "файл больше 20 МБ — откройте в группе"
NOTE_NOT_STORED: Final = "файл не сохранён — откройте в группе"
# Сколько прежних текстов правки хранится в сообщении.
MAX_PREVIOUS_TEXTS: Final = 10

Access = Literal["ok", "admin_required"]
Status = Literal["pending", "bound", "unbound", "removed"]


def new_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str:
    return "".join(raw.split()).upper()


def code_expiry(now: datetime) -> datetime:
    return now + CODE_TTL


def access_of(*, bot_is_admin: bool, can_pin: bool) -> Access:
    """Читать всё и закреплять бот может только администратором с правом закрепа."""
    return "ok" if bot_is_admin and can_pin else "admin_required"


CODE_MESSAGE: Final = {
    "ru": (
        "Чтобы подключить группу к клиенту, введите в Платформе код: {code}. "
        "Код действует 48 часов. Новый код — команда /connect."
    ),
    "uz": (
        "Guruhni mijozga ulaş uçun Platformada kodni kiriting: {code}. "
        "Kod 48 soat amal qiladi. Yangi kod — /connect buyruği."
    ),
    "en": (
        "To connect this group to a client, enter the code in the Platform: {code}. "
        "The code is valid for 48 hours. Send /connect for a new one."
    ),
}
NEEDS_ADMIN_MESSAGE: Final = {
    "ru": "Сделайте бота администратором группы с правом закреплять сообщения.",
    "uz": "Botni guruh administratori qiling va xabarlarni mahkamlaş huquqini bering.",
    "en": "Make the bot a group administrator with the right to pin messages.",
}
NOTICE: Final = {
    "ru": "Сообщения и файлы этой группы сохраняются в карточке клиента RailTech.",
    "uz": "Bu guruhning xabarlari va fayllari RailTech mijoz kartoçkasida saqlanadi.",
    "en": "Messages and files of this group are saved in the RailTech client card.",
}


def text(table: dict[str, str], language: str | None, **values: str) -> str:
    return table.get(language or "ru", table["ru"]).format(**values)


# Подкоды `details.reason` — строками вне `Reason`: enum в схеме ответов не расширяется,
# контракт остаётся аддитивным (как у второго фактора, `domain/errors.py`).
GROUP_CODE_INVALID: Final = "group_code_invalid"
GROUP_CODE_EXPIRED: Final = "group_code_expired"
GROUP_ALREADY_BOUND: Final = "group_already_bound"
GROUP_IS_TEAM_CHANNEL: Final = "group_is_team_channel"
GROUP_NOT_BOUND: Final = "group_not_bound"
