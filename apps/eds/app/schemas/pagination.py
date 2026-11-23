"""Курсорная пагинация (eds.yaml, «Списки»): курсор непрозрачный, порядок — от новых к старым, ключ (время, id)."""

import base64
import binascii
import datetime as dt
import json
import uuid
from typing import Annotated

from fastapi import Query

from app.errors import invalid_fields

Cursor = Annotated[str | None, Query(max_length=1200)]
Limit = Annotated[int, Query(ge=1, le=100)]
#: Порядок списка (Х-15б): `field` по возрастанию, `-field` по убыванию; поля — `number|subject|status|amount|created`.
Sort = Annotated[str | None, Query(pattern=r"^-?(number|subject|status|amount|created)$")]


def encode_cursor(moment: dt.datetime, key: uuid.UUID) -> str:
    raw = json.dumps({"t": moment.isoformat(), "k": str(key)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str | None) -> tuple[dt.datetime, uuid.UUID] | None:
    """Разобрать курсор; чужой или повреждённый — 422 `VALIDATION_FAILED` (`cursor`)."""
    if value is None:
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        moment = dt.datetime.fromisoformat(raw["t"])
        if moment.tzinfo is None:
            raise ValueError("naive")
        return moment, uuid.UUID(raw["k"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise invalid_fields("Неверный курсор.", cursor="malformed") from exc


def encode_sort_cursor(sort: str, value: str | None, key: uuid.UUID) -> str:
    """Курсор списка с порядком по полю: порядок (`sort`), значение поля последней строки (`None` — пусто) и id."""
    raw = json.dumps({"s": sort, "v": value, "k": str(key)}, ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_sort_cursor(value: str | None, sort: str) -> tuple[str | None, uuid.UUID] | None:
    """Разобрать курсор порядка `sort`; курсор другого порядка или повреждённый — 422 `VALIDATION_FAILED` (`cursor`)."""
    if value is None:
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if raw["s"] != sort:
            raise ValueError("other order")
        field = raw["v"]
        if field is not None and not isinstance(field, str):
            raise ValueError("value")
        return field, uuid.UUID(raw["k"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise invalid_fields("Неверный курсор.", cursor="malformed") from exc
