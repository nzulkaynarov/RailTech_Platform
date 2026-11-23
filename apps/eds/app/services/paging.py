"""Курсорная пагинация списков: порядок от новых к старым, ключ (время, id); страница на один элемент длиннее лимита."""

import datetime as dt
import uuid
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import ColumnElement, Select, and_, func, or_, tuple_

from app.errors import invalid_fields
from app.schemas.pagination import decode_sort_cursor, encode_cursor, encode_sort_cursor

#: Допустимые поля порядка списка (Х-15б): ключ параметра `sort` (`field` — по возрастанию, `-field` — по убыванию) →
#: вид значения. Поле вне списка не принимается: маршрут отдаёт 422 по шаблону из контракта, а не применяет его молча.
SortKind = Literal["text", "number", "time"]
SORT_FIELDS: dict[str, SortKind] = {
    "number": "text",
    "subject": "text",
    "status": "text",
    "amount": "number",
    "created": "time",
}


def apply(
    stmt: Select[Any],
    moment: Any,
    key: Any,
    cursor: tuple[dt.datetime, uuid.UUID] | None,
    limit: int,
) -> Select[Any]:
    """Условие «старше курсора», порядок и лимит+1. `moment` и `key` — столбцы ORM или подзапроса."""
    if cursor is not None:
        stmt = stmt.where(tuple_(moment, key) < tuple_(*cursor))
    return stmt.order_by(moment.desc(), key.desc()).limit(limit + 1)


def cut[T](
    rows: Sequence[T], limit: int, moment_of: Callable[[T], dt.datetime], key_of: Callable[[T], uuid.UUID]
) -> tuple[list[T], str | None]:
    """Страница и курсор следующей (`None` — страниц больше нет)."""
    page = list(rows[:limit])
    if len(rows) <= limit:
        return page, None
    last = page[-1]
    return page, encode_cursor(moment_of(last), key_of(last))


def parse_sort(raw: str | None) -> tuple[str, bool] | None:
    """`field` / `-field` → (поле, по убыванию); без значения или поле вне списка — `None` (порядок по умолчанию)."""
    if not raw:
        return None
    desc = raw.startswith("-")
    field = raw[1:] if desc else raw
    return (field, desc) if field in SORT_FIELDS else None


def _expr(column: Any, kind: SortKind) -> Any:
    # Пустая строка — такое же «нет значения», как NULL: номер без значения всегда в конце
    return func.nullif(column, "") if kind == "text" else column


def _text(value: Any, kind: SortKind) -> str | None:
    if value is None or (kind == "text" and value == ""):
        return None
    return value.isoformat() if isinstance(value, dt.datetime) else str(value)


def _typed(value: str, kind: SortKind) -> Any:
    try:
        if kind == "number":
            return Decimal(value)
        if kind == "time":
            return dt.datetime.fromisoformat(value)
    except (InvalidOperation, ValueError) as exc:
        raise invalid_fields("Неверный курсор.", cursor="malformed") from exc
    return value


def apply_sorted(
    stmt: Select[Any],
    column: ColumnElement[Any],
    key: Any,
    sort: tuple[str, bool],
    cursor: str | None,
    limit: int,
) -> Select[Any]:
    """Порядок по полю `sort` с курсором: ключ (значение, id), пустые значения всегда в конце при любом направлении.

    Курсор помнит значение поля последней строки и её id (второй ключ, чтобы равные значения не терялись и не
    повторялись); сменился порядок — прежний курсор не подходит и отклоняется.
    """
    field, desc = sort
    kind = SORT_FIELDS[field]
    value = _expr(column, kind)
    raw = f"-{field}" if desc else field
    after = decode_sort_cursor(cursor, raw)
    if after is not None:
        last, last_key = after
        later_key = key < last_key if desc else key > last_key
        if last is None:
            stmt = stmt.where(and_(value.is_(None), later_key))
        else:
            typed = _typed(last, kind)
            later = value < typed if desc else value > typed
            stmt = stmt.where(or_(later, and_(value == typed, later_key), value.is_(None)))
    ordered = value.desc().nulls_last() if desc else value.asc().nulls_last()
    return stmt.order_by(ordered, key.desc() if desc else key.asc()).limit(limit + 1)


def cut_sorted[T](
    rows: Sequence[T],
    limit: int,
    sort: tuple[str, bool],
    value_of: Callable[[T], Any],
    key_of: Callable[[T], uuid.UUID],
) -> tuple[list[T], str | None]:
    """Страница и курсор следующей для порядка `sort` (`None` — страниц больше нет)."""
    page = list(rows[:limit])
    if len(rows) <= limit:
        return page, None
    field, desc = sort
    last = page[-1]
    return page, encode_sort_cursor(
        f"-{field}" if desc else field, _text(value_of(last), SORT_FIELDS[field]), key_of(last)
    )
