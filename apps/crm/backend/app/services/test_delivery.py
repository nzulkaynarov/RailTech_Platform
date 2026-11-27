"""ТЕСТ-2: единый шлюз доставки сотрудникам по ERP- и EDS-событиям (колокольчик, Telegram).

Здесь, и только здесь, такие уведомления пишутся: строка колокольчика (`add_in`) и сообщение
Telegram (`"kind": "staff"`). Запись тестовой компании получает только сотрудник с включённым
«Показывать тестовые» (`users.show_test`); остальные не получают ничего. Клиентская сторона
(контакт тестовой компании в кабинете) не затрагивается: проход кабинета её ждёт. Охранный тест
`tests/unit/test_delivery_guard.py` требует, чтобы ни `add_in`, ни `"kind": "staff"` не
встречались в модулях ERP- и EDS-уведомлений вне этого файла.
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.services import staff_notifications

TelegramFilter = Callable[[AsyncSession, Sequence[int]], Awaitable[list[int]]]


async def allowed(session: AsyncSession, user_ids: Sequence[int], *, test: bool) -> list[int]:
    """Кому из `user_ids` доставлять: рабочая запись — всем, тестовая — с показом тестовых."""
    ids = list(dict.fromkeys(user_ids))
    if not test or not ids:
        return ids
    rows = await session.scalars(select(User.id).where(User.id.in_(ids), User.show_test.is_(True)))
    on = set(rows.all())
    return [uid for uid in ids if uid in on]


async def deliver_staff(
    session: AsyncSession,
    user_ids: Sequence[int],
    *,
    test: bool,
    bell: dict[str, Any] | None = None,
    text: str | None = None,
    telegram_for: TelegramFilter | None = None,
) -> list[dict[str, Any]]:
    """Колокольчик (`bell` — аргументы `add_in`) и элементы Telegram (`text`) для прошедших шлюз.

    Возвращает элементы для `ErpEventNotices.add` (Telegram уйдёт после коммита)."""
    people = await allowed(session, user_ids, test=test)
    if not people:
        return []
    if bell is not None:
        staff_notifications.add_in(session, people, **bell)
    if text is None:
        return []
    chosen = await telegram_for(session, people) if telegram_for is not None else people
    return [{"kind": "staff", "user_id": uid, "text": text} for uid in chosen]
