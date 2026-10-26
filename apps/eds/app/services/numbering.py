"""Нумерация реестра EDS (runbook волны 12 §2.1; CONVENTIONS.md §2 п. 6).

Счётчик — строка на (тип, год) в `number_counters` под `SELECT … FOR UPDATE` в той же транзакции, что и создание
документа: параллельные запросы встают в очередь на строке, откат возвращает счётчик — пропусков нет. Выданный номер
обратно не возвращается: отменённый документ остаётся в реестре. Год — по `Asia/Tashkent`.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import company_year
from app.models import NumberCounter


class NumberKind(StrEnum):
    LETTER_IN = "letter_in"  # ВХ-NNN/ГГ
    OUTGOING = "outgoing"  # ИСХ-NNN/ГГ: письмо при отправке и КП при одобрении — один счётчик
    MEMO = "memo"  # СЗ-ГГГГ/NNN
    APPLICATION = "application"  # ЗЯ-ГГГГ/NNN
    REPORT = "report"  # ОТ-ГГГГ/NNN


_PREFIX = {
    NumberKind.LETTER_IN: "ВХ",
    NumberKind.OUTGOING: "ИСХ",
    NumberKind.MEMO: "СЗ",
    NumberKind.APPLICATION: "ЗЯ",
    NumberKind.REPORT: "ОТ",
}
_YEAR_SUFFIX = {NumberKind.LETTER_IN, NumberKind.OUTGOING}  # ВХ-104/26, ИСХ-082/26; прочие — СЗ-2026/031


def format_number(kind: NumberKind, year: int, value: int) -> str:
    prefix = _PREFIX[kind]
    if kind in _YEAR_SUFFIX:
        return f"{prefix}-{value:03d}/{year % 100:02d}"
    return f"{prefix}-{year}/{value:03d}"


async def allocate(session: AsyncSession, kind: NumberKind, moment: datetime) -> str:
    """Выдать следующий номер типа за год момента. Вызывать в транзакции создания документа."""
    year = company_year(moment)
    # Первая выдача года: строки ещё нет — параллельные вставки не падают, проигравший ждёт и берёт блокировку ниже.
    await session.execute(
        insert(NumberCounter).values(kind=kind.value, year=year, last_value=0).on_conflict_do_nothing()
    )
    counter = (
        await session.execute(
            select(NumberCounter)
            .where(NumberCounter.kind == kind.value, NumberCounter.year == year)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    counter.last_value += 1
    await session.flush()
    return format_number(kind, year, counter.last_value)
