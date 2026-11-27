"""ТЕСТ-2: единый шлюз доставки сотрудникам по записям тестовых компаний (колокольчик, Telegram).

Уведомление о записи тестовой компании получает только сотрудник с включённым «Показывать
тестовые» (`users.show_test`); остальные не получают ничего. Клиентская сторона (контакт
тестовой компании в кабинете) не затрагивается: проход кабинета её ждёт. Доставки сотрудникам
по ERP- и EDS-событиям идут через `allowed`; новую доставку вне шлюза ловит охранный тест
`tests/unit/test_delivery_guard.py`.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User


async def allowed(session: AsyncSession, user_ids: Sequence[int], *, test: bool) -> list[int]:
    """Кому из `user_ids` доставлять: рабочая запись — всем, тестовая — с показом тестовых."""
    ids = list(dict.fromkeys(user_ids))
    if not test or not ids:
        return ids
    rows = await session.scalars(select(User.id).where(User.id.in_(ids), User.show_test.is_(True)))
    on = set(rows.all())
    return [uid for uid in ids if uid in on]
