"""Нумерация реестра EDS (runbook волны 12 §2.1; CONVENTIONS.md §2 п. 6).

Счётчик — строка на (тип, год) в `number_counters` под `SELECT … FOR UPDATE` в той же транзакции, что и создание
документа: параллельные запросы встают в очередь на строке, откат возвращает счётчик — пропусков нет. Выданный номер
обратно не возвращается: отменённый документ остаётся в реестре. Год — по `Asia/Tashkent`.

Обозначения видов (задача «Н», решение владельца 2026-11-13) задаёт владелец в «Настройки · Нумерация»
(`number_labels`); только латиница и цифры, номер одинаков на всех языках. Номер выдан раз и остаётся прежним, пока
его не перенумеровали разово (`python -m app renumber-latin`, СЦ-5: ВХ-104/26 → IN-104/26); прежний номер хранится в
`previous_number` и находится поиском. Код не разбирает номер по обозначению — номер непрозрачен.
"""

import re
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import company_year
from app.errors import invalid_fields
from app.models import NumberCounter, NumberLabel


class NumberKind(StrEnum):
    LETTER_IN = "letter_in"  # IN-NNN/ГГ
    OUTGOING = "outgoing"  # OUT-NNN/ГГ: письмо при отправке и КП при одобрении — один счётчик
    MEMO = "memo"  # MEMO-ГГГГ/NNN
    APPLICATION = "application"  # APP-ГГГГ/NNN
    REPORT = "report"  # REP-ГГГГ/NNN


DEFAULT_LABELS: dict[NumberKind, str] = {
    NumberKind.LETTER_IN: "IN",
    NumberKind.OUTGOING: "OUT",
    NumberKind.MEMO: "MEMO",
    NumberKind.APPLICATION: "APP",
    NumberKind.REPORT: "REP",
}
_YEAR_SUFFIX = {NumberKind.LETTER_IN, NumberKind.OUTGOING}  # IN-104/26, OUT-082/26; прочие — MEMO-2026/031
# Обозначение — только латиница и цифры (СЦ-5): один алфавит на всех языках, номер читается и ищется одинаково
_LABEL = re.compile(r"^[A-Z0-9]{1,16}$")


def format_number(kind: NumberKind, year: int, value: int, label: str | None = None) -> str:
    prefix = label or DEFAULT_LABELS[kind]
    if kind in _YEAR_SUFFIX:
        return f"{prefix}-{value:03d}/{year % 100:02d}"
    return f"{prefix}-{year}/{value:03d}"


async def labels(session: AsyncSession) -> dict[NumberKind, str]:
    """Действующие обозначения всех видов: заданные владельцем поверх умолчаний."""
    rows = (await session.execute(select(NumberLabel.kind, NumberLabel.label))).all()
    stored: dict[str, str] = {kind: label for kind, label in rows}  # noqa: C416 — строки Row, не пары
    return {kind: stored.get(kind.value) or default for kind, default in DEFAULT_LABELS.items()}


async def set_labels(session: AsyncSession, values: dict[str, str]) -> dict[NumberKind, str]:
    """Сохранить обозначения. Неизвестный вид, пустое или не из латиницы и цифр (до 16 знаков) — 422; обозначение не
    может совпасть с обозначением другого вида."""
    current = await labels(session)
    wanted = dict(current)
    for key, raw in values.items():
        try:
            kind = NumberKind(key)
        except ValueError:
            raise invalid_fields("Неизвестный вид номера.", **{f"labels.{key}": "unknown_kind"}) from None
        label = raw.strip()
        if not _LABEL.fullmatch(label):
            raise invalid_fields(
                "Обозначение: до 16 знаков, только латинские буквы и цифры.", **{f"labels.{key}": "invalid_label"}
            )
        wanted[kind] = label
    for kind, label in wanted.items():
        taken = {v.casefold() for k, v in wanted.items() if k != kind}
        if label.casefold() in taken:
            raise invalid_fields(
                "Такое обозначение уже у другого вида номера.", **{f"labels.{kind.value}": "label_taken"}
            )
    for kind, label in wanted.items():
        if label != current[kind]:
            await session.execute(
                insert(NumberLabel)
                .values(kind=kind.value, label=label)
                .on_conflict_do_update(index_elements=[NumberLabel.kind], set_={"label": label})
            )
    await session.flush()
    return wanted


def examples(current: dict[NumberKind, str], moment: datetime) -> list[tuple[NumberKind, str, str]]:
    """(вид, обозначение, образец первого номера года) — для образца в редакторе."""
    year = company_year(moment)
    return [(kind, label, format_number(kind, year, 1, label)) for kind, label in current.items()]


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
    current = (await labels(session))[kind]
    return format_number(kind, year, counter.last_value, current)
