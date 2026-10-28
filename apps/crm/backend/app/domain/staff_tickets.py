"""Обращения сотрудников к администратору (W15-H7): темы, статусы, значения, лимит. Чистые функции.

Обращение пишет сам сотрудник с экрана «Нет доступа» или из «Помощи»; адрес страницы и роль
подставляет Платформа. Админ отвечает и двигает статус «Новое → В работе → Решено». Решения и
данные — в CRM (ADR-0015); правила живут здесь, чтобы их проверяли тесты без БД, запись —
`services/staff_tickets.py`.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

SUBJECTS: Final = ("access", "notification", "template", "error", "other")
STATUSES: Final = ("new", "in_progress", "resolved")
Subject = Literal["access", "notification", "template", "error", "other"]
Status = Literal["new", "in_progress", "resolved"]

BODY_MAX_LEN: Final = 4000
REPLY_MAX_LEN: Final = 4000
PAGE_MAX_LEN: Final = 300
ROLE_MAX_LEN: Final = 120
# Не больше пяти обращений в час от одного сотрудника: защита администратора от потока.
MAX_PER_HOUR: Final = 5
WINDOW: Final = timedelta(hours=1)
NUMBER_PREFIX: Final = "ОБР"

_NUMBER: Final = re.compile(rf"^{NUMBER_PREFIX}-(\d{{1,9}})$")
# Переходы статуса: «Решено» можно вернуть «В работу» (проблема вернулась).
_MOVES: Final[dict[str, frozenset[str]]] = {
    "new": frozenset({"in_progress", "resolved"}),
    "in_progress": frozenset({"resolved"}),
    "resolved": frozenset({"in_progress"}),
}


class TicketValueError(ValueError):
    """Значение не прошло проверку; `reason` — подкод для `details.reason`, `field` — поле формы."""

    def __init__(self, reason: str, field: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.reason = reason
        self.field = field


def checked_subject(value: str) -> Subject:
    if value not in SUBJECTS:
        raise TicketValueError("ticket_subject_unknown", "subject")
    return value  # type: ignore[return-value]


def checked_status(value: str) -> Status:
    if value not in STATUSES:
        raise TicketValueError("ticket_status_unknown", "status")
    return value  # type: ignore[return-value]


def checked_body(text: str) -> str:
    value = text.strip()
    if not value:
        raise TicketValueError("ticket_text_empty", "body")
    if len(value) > BODY_MAX_LEN:
        raise TicketValueError("ticket_text_too_long", "body")
    return value


def checked_reply(text: str) -> str:
    value = text.strip()
    if not value:
        raise TicketValueError("ticket_reply_empty", "body")
    if len(value) > REPLY_MAX_LEN:
        raise TicketValueError("ticket_reply_too_long", "body")
    return value


def checked_page(page: str | None) -> str | None:
    """Путь страницы Платформы (`/eds/inbox`): только внутренний, без схемы и хоста.

    Слишком длинный путь обрезается до `PAGE_MAX_LEN`, а не отклоняется: обращение важнее адреса.
    """
    if page is None:
        return None
    value = page.strip()
    if not value:
        return None
    if not value.startswith("/") or value.startswith("//"):
        raise TicketValueError("ticket_page_invalid", "page")
    if any(ord(ch) < 32 or ch in "\\<>" for ch in value):
        raise TicketValueError("ticket_page_invalid", "page")
    return value[:PAGE_MAX_LEN]


def clipped_role(role: str | None) -> str | None:
    """Названия ролей автора на момент обращения — для админа, без права что-то решать по ним."""
    if role is None:
        return None
    value = role.strip()[:ROLE_MAX_LEN]
    return value or None


def can_move(current: str, target: str) -> bool:
    return target in _MOVES.get(current, frozenset())


def rate_exceeded(recent: int) -> bool:
    return recent >= MAX_PER_HOUR


def window_start(now: datetime) -> datetime:
    return now - WINDOW


def number_of(ticket_id: int) -> str:
    """`ОБР-0012`: номер обращения для людей; в адресах и API — числовой id."""
    return f"{NUMBER_PREFIX}-{ticket_id:04d}"


def id_of(number: str) -> int | None:
    match = _NUMBER.match(number.strip())
    return int(match.group(1)) if match else None


def after_reply(current: str) -> Status:
    """Ответ админа на новое обращение берёт его в работу; решённое остаётся решённым."""
    return "in_progress" if current == "new" else current  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ReplyNote:
    """Что уходит автору в колокольчик: заголовок и подпись (без служебных слов, с номером)."""

    title: str
    subtitle: str


_NOTE_TITLE: Final = {
    "ru": "Ответ на обращение {number}",
    "uz": "{number} murojaatiga javob",
    "en": "Reply to request {number}",
}
_STATUS_TITLE: Final = {
    "ru": "Обращение {number} решено",
    "uz": "{number} murojaati hal qilindi",
    "en": "Request {number} is resolved",
}
_TELEGRAM: Final = {
    "ru": ("Администратор ответил на ваше обращение {number}:\n{text}", "Открыть"),
    "uz": ("Administrator {number} murojaatingizga javob berdi:\n{text}", "Ochish"),
    "en": ("The administrator replied to your request {number}:\n{text}", "Open"),
}
_SNIPPET: Final = 110


def snippet(text: str, limit: int = _SNIPPET) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def reply_note(language: str | None, number: str, text: str) -> ReplyNote:
    lang = language if language in _NOTE_TITLE else "ru"
    return ReplyNote(_NOTE_TITLE[lang].format(number=number), snippet(text))


def resolved_note(language: str | None, number: str, text: str) -> ReplyNote:
    lang = language if language in _STATUS_TITLE else "ru"
    return ReplyNote(_STATUS_TITLE[lang].format(number=number), snippet(text))


def telegram_text(language: str | None, number: str, text: str, link: str) -> str:
    """Ответ автору в Telegram; строка «Открыть» — только если адрес Платформы известен."""
    lang = language if language in _TELEGRAM else "ru"
    body, open_label = _TELEGRAM[lang]
    message = body.format(number=number, text=snippet(text, 500))
    return f"{message}\n{open_label}: {link}" if link else message
