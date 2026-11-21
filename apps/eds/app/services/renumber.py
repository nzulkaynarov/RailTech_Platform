"""Разовая перенумерация на латиницу (СЦ-5): `python -m app renumber-latin`.

Номера, выданные с кириллическим обозначением (ВХ-001/26, ИСХ-001/26, СЗ-…, ЗЯ-…), заменяются по карте
`{старый номер: новый номер}`, общей для всех систем. Свои таблицы EDS:

* `letters.number`, `documents.number` — меняется номер, прежний уходит в `previous_number` (если там уже есть более
  ранний номер, он остаётся: именно он стоит в отправленных и подписанных PDF);
* копии номера других записей — `letters.deal_number`, `documents.deal_number`, `approval_routes.deal_number`,
  `project_documents.deal_number`, `approval_routes.outgoing_number` и номера внутри заголовков
  `approval_routes.title`, `project_documents.title`.

История не трогается: журнал, события шины, PDF на бланке. Повтор ничего не меняет: изменяется только значение,
которое ещё равно ключу карты. Код номера не разбирает; `emit_mapping` — единственное место, где обозначение
отрезается от номера (разово, из действующих обозначений видов), и результат проверяется человеком до `--apply`.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRoute, Document, Letter, ProjectDocument
from app.services import numbering
from app.services.numbering import NumberKind

_KIND_BY_DOCUMENT = {
    "letter_out": NumberKind.OUTGOING,
    "memo": NumberKind.MEMO,
    "application": NumberKind.APPLICATION,
    "report": NumberKind.REPORT,
}
_LATIN_NUMBER = re.compile(r"^[A-Z0-9]{1,16}-")


@dataclass(frozen=True)
class Change:
    table: str
    column: str
    id: object
    old: str
    new: str

    def line(self) -> str:
        return f"{self.table}.{self.column} {self.id}: {self.old} → {self.new}"


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    writes: list[tuple[Any, str, str]] = field(default_factory=list)  # (запись, поле, новое значение)

    def set(self, row: Any, table: str, column: str, old: str, new: str) -> None:
        self.changes.append(Change(table, column, row.id, old, new))
        self.writes.append((row, column, new))


def _clean(mapping: Mapping[str, str]) -> dict[str, str]:
    return {old.strip(): new.strip() for old, new in mapping.items() if old.strip() != new.strip()}


def replace_numbers(text: str, mapping: Mapping[str, str]) -> str:
    """Заменить в тексте целые номера из карты; «ВХ-001/26» не находится внутри «ВХ-001/260»."""
    if not mapping:
        return text
    keys = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w/-])(" + "|".join(re.escape(k) for k in keys) + r")(?![\w/])")
    return pattern.sub(lambda m: mapping[m.group(1)], text)


async def emit_mapping(session: AsyncSession) -> dict[str, str]:
    """Карта СВОИХ номеров EDS: номер с обозначением не из латиницы получает действующее обозначение вида."""
    current = await numbering.labels(session)
    result: dict[str, str] = {}
    letters = (await session.execute(select(Letter.number))).scalars().all()
    documents = (
        await session.execute(select(Document.kind, Document.number).where(Document.number.is_not(None)))
    ).all()
    rows = [(NumberKind.LETTER_IN, n) for n in letters] + [(_KIND_BY_DOCUMENT[k], n) for k, n in documents if n]
    for kind, number in rows:
        if _LATIN_NUMBER.match(number) or "-" not in number:
            continue
        result[number] = current[kind] + number[number.index("-") :]
    return result


async def _numbers(session: AsyncSession, model: Any, table: str, mapping: dict[str, str], plan: Plan) -> None:
    for row in (await session.execute(select(model).where(model.number.in_(list(mapping))))).scalars():
        new = mapping[row.number]
        plan.set(row, table, "number", row.number, new)
        if row.previous_number is None:
            plan.set(row, table, "previous_number", "∅", row.number)


async def _copies(
    session: AsyncSession, model: Any, table: str, columns: list[str], mapping: dict[str, str], plan: Plan
) -> None:
    for row in (await session.execute(select(model))).scalars():
        for column in columns:
            old = getattr(row, column)
            if old:
                new = replace_numbers(old, mapping) if column == "title" else mapping.get(old, old)
                if new != old:
                    plan.set(row, table, column, old, new)


async def _present(session: AsyncSession, mapping: dict[str, str]) -> dict[str, str]:
    """Часть карты, чьи старые номера ещё стоят в реестре: повтор не спорит со своим же результатом."""
    keys = list(mapping)
    found: set[str] = set()
    for model in (Letter, Document):
        rows = (await session.execute(select(model.number).where(model.number.in_(keys)))).scalars()
        found |= {n for n in rows if n}
    return {old: new for old, new in mapping.items() if old in found}


async def _check_clashes(session: AsyncSession, mapping: dict[str, str], plan: Plan) -> None:
    active = await _present(session, mapping)
    new_values = list(active.values())
    for new in sorted({n for n in new_values if new_values.count(n) > 1}):
        plan.errors.append(f"два старых номера дают один новый: {new}")
    taken: set[str] = set()
    for model in (Letter, Document):
        found = (await session.execute(select(model.number).where(model.number.in_(new_values)))).scalars()
        taken |= {n for n in found if n}
    for new in sorted(taken - set(active)):
        plan.errors.append(f"новый номер уже занят другой записью: {new}")


async def build_plan(session: AsyncSession, raw_mapping: Mapping[str, str]) -> Plan:
    mapping = _clean(raw_mapping)
    plan = Plan()
    await _check_clashes(session, mapping, plan)
    await _numbers(session, Letter, "letters", mapping, plan)
    await _numbers(session, Document, "documents", mapping, plan)
    await _copies(session, Letter, "letters", ["deal_number"], mapping, plan)
    await _copies(session, Document, "documents", ["deal_number"], mapping, plan)
    await _copies(session, ApprovalRoute, "approval_routes", ["deal_number", "outgoing_number", "title"], mapping, plan)
    await _copies(session, ProjectDocument, "project_documents", ["deal_number", "title"], mapping, plan)
    return plan


async def apply_plan(session: AsyncSession, plan: Plan) -> None:
    """Записать план в транзакции вызывающего; при ошибках плана не пишет ничего."""
    if plan.errors:
        raise ValueError("; ".join(plan.errors))
    for row, column, value in plan.writes:
        setattr(row, column, value)
    await session.flush()
