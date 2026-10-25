"""Курсорная пагинация списков: порядок от новых к старым, ключ (время, id); страница на один элемент длиннее лимита."""

import datetime as dt
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import Select, tuple_

from app.schemas.pagination import encode_cursor


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
