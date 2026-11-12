"""Справочники документооборота как данные (EDS-REG; `docs/research/2026-11-02-flexibility/4-settings-ia.md` §4.3).

Значения — данные администратора (название ru/uz/en, порядок, «действует», поля вида); **поведение — код из закрытого
списка** (`SPECS`): какие справочники бывают, какие у значения поля и что они значат (`urgent` — регистрация сразу
«срочно», `due_days` — срок исполнения по умолчанию), где значение используется. Письмо хранит код строкой.

* Код значения создаёт EDS из названия (латиница, `^[a-z][a-z_]{0,31}$`) и не меняет: письма хранят код.
* Использованное значение не удаляется — его скрывают (`active = false`): в формах его нет, у старых писем остаётся.
* Закрытый справочник (`closed`, поведение кода) — только переименовать и переставить.
* Каждое изменение — строка журнала EDS (`dictionary.*`, кто и что) в той же транзакции.
"""

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app import clock
from app.errors import conflict, invalid_fields, not_found
from app.models import DictionaryItem, Letter, SigningAuthority
from app.schemas.dictionaries import (
    AttrValue,
    Dictionary,
    DictionaryAttr,
    DictionaryItemIn,
    DictionaryItemList,
    DictionaryItemPatch,
    DictionaryList,
    LocalizedName,
)
from app.schemas.dictionaries import DictionaryItem as ItemOut
from app.services import journal

LETTER_KINDS: Final = "letter-kinds"
RECEIPT_METHODS: Final = "receipt-methods"
RESOLUTION_KINDS: Final = "resolution-kinds"
SIGNING_KINDS: Final = "signing-kinds"
CLOSE_REASONS: Final = "close-reasons"
POSITION_STEP = 10


@dataclass(frozen=True, slots=True)
class Attr:
    key: str
    type: Literal["boolean", "integer"]
    name: tuple[str, str, str]  # ru, uz, en
    minimum: int | None = None
    maximum: int | None = None

    def default(self) -> AttrValue:
        return False if self.type == "boolean" else None

    def check(self, value: Any) -> bool:
        if value is None:
            return self.type == "integer"
        if self.type == "boolean":
            return isinstance(value, bool)
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return (self.minimum is None or value >= self.minimum) and (self.maximum is None or value <= self.maximum)


@dataclass(frozen=True, slots=True)
class Spec:
    kind: str
    name: tuple[str, str, str]
    usage: InstrumentedAttribute[Any]  # колонка письма, где хранится код: использованное значение не удаляется
    attrs: tuple[Attr, ...] = ()
    closed: bool = False


SPECS: Final[dict[str, Spec]] = {
    spec.kind: spec
    for spec in (
        Spec(
            LETTER_KINDS,
            ("Виды входящих документов", "Kiruvchi hujjat turlari", "Incoming document types"),
            Letter.doc_kind,
            attrs=(
                Attr("urgent", "boolean", ("Срочный", "Shoshilinch", "Urgent")),
                Attr(
                    "due_days",
                    "integer",
                    ("Срок исполнения, дней", "Ijro muddati, kun", "Due in, days"),
                    minimum=1,
                    maximum=365,
                ),
            ),
        ),
        Spec(
            RECEIPT_METHODS,
            ("Способы получения", "Qabul qilish usullari", "Receipt methods"),
            Letter.receipt_method,
        ),
        # Виды резолюции — поведение системы (поручение, ответ, ознакомление): только переименовать и переставить.
        Spec(
            RESOLUTION_KINDS,
            ("Виды резолюции", "Rezolyutsiya turlari", "Resolution types"),
            Letter.resolution_kind,
            closed=True,
        ),
        # Виды документов, которые подписывают по полномочию (SIGN-2, ADR-0024 п. 1): открытый каталог — вид добавляет
        # администратор; использованный в полномочии вид не удаляется, а скрывается.
        # Причины «Закрыть без ответа» (решение владельца 2026-11-11): открытый справочник; `comment_required` —
        # ответственный обязан пояснить (недобросовестный контрагент, другое).
        Spec(
            CLOSE_REASONS,
            ("Причины закрытия без ответа", "Javobsiz yopish sabablari", "Reasons to close without reply"),
            Letter.close_reason,
            attrs=(Attr("comment_required", "boolean", ("Нужно пояснение", "Izoh kerak", "Comment required")),),
        ),
        Spec(
            SIGNING_KINDS,
            ("Виды документов для подписи", "Imzolanadigan hujjat turlari", "Document types for signing"),
            SigningAuthority.kinds,
        ),
    )
}


def _spec(kind: str) -> Spec:
    spec = SPECS.get(kind)
    if spec is None:
        raise not_found("Такого справочника нет.")
    return spec


def _names(values: tuple[str, str, str]) -> LocalizedName:
    return LocalizedName(ru=values[0], uz=values[1], en=values[2])


def catalog() -> DictionaryList:
    return DictionaryList(
        items=[
            Dictionary(
                kind=spec.kind,
                name=_names(spec.name),
                closed=spec.closed,
                attrs=[
                    DictionaryAttr(key=a.key, type=a.type, name=_names(a.name), minimum=a.minimum, maximum=a.maximum)
                    for a in spec.attrs
                ],
            )
            for spec in SPECS.values()
        ]
    )


def present(row: DictionaryItem, spec: Spec, used: bool | None = None) -> ItemOut:
    attrs = {a.key: row.attrs.get(a.key, a.default()) for a in spec.attrs}
    return ItemOut(
        code=row.code,
        name=LocalizedName(ru=row.name_ru, uz=row.name_uz, en=row.name_en),
        attrs=attrs,
        active=row.active,
        position=row.position,
        used=used,
    )


async def _rows(session: AsyncSession, kind: str, *, include_hidden: bool) -> list[DictionaryItem]:
    stmt = select(DictionaryItem).where(DictionaryItem.kind == kind)
    if not include_hidden:
        stmt = stmt.where(DictionaryItem.active.is_(True))
    return list((await session.execute(stmt.order_by(DictionaryItem.position, DictionaryItem.code))).scalars())


async def _used_codes(session: AsyncSession, spec: Spec) -> set[str]:
    column = spec.usage
    if isinstance(column.type, ARRAY):  # поле-массив кодов (виды документов полномочия подписи)
        rows = await session.execute(select(func.unnest(column)).distinct())
        return {code for code in rows.scalars() if code}
    rows = await session.execute(select(column).where(column.is_not(None)).group_by(column))
    return {code for code in rows.scalars() if code}


async def list_items(session: AsyncSession, kind: str, *, include_hidden: bool = False) -> DictionaryItemList:
    spec = _spec(kind)
    rows = await _rows(session, kind, include_hidden=include_hidden)
    used = await _used_codes(session, spec) if include_hidden else None
    return DictionaryItemList(items=[present(row, spec, None if used is None else row.code in used) for row in rows])


async def find(session: AsyncSession, kind: str, code: str, *, active_only: bool = True) -> DictionaryItem | None:
    """Значение справочника по коду; по умолчанию — только действующее (регистрация письма)."""
    row = await session.get(DictionaryItem, (kind, code))
    if row is None or (active_only and not row.active):
        return None
    return row


async def _get(session: AsyncSession, kind: str, code: str, *, lock: bool = False) -> DictionaryItem:
    stmt = select(DictionaryItem).where(DictionaryItem.kind == kind, DictionaryItem.code == code)
    if lock:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise not_found("Такого значения в справочнике нет.")
    return row


def _clean_attrs(spec: Spec, values: dict[str, AttrValue], base: dict[str, Any]) -> dict[str, Any]:
    known = {a.key: a for a in spec.attrs}
    bad = {key: "unknown_attr" for key in values if key not in known}
    bad |= {key: "invalid_value" for key, value in values.items() if key in known and not known[key].check(value)}
    if bad:
        raise invalid_fields("Проверьте поля значения.", **{f"attrs.{key}": why for key, why in bad.items()})
    merged = {a.key: base.get(a.key, a.default()) for a in spec.attrs}
    merged.update(values)
    return merged


async def _name_taken(session: AsyncSession, kind: str, name: str, *, except_code: str | None = None) -> bool:
    stmt = select(func.count()).where(
        DictionaryItem.kind == kind, func.lower(DictionaryItem.name_ru) == name.strip().lower()
    )
    if except_code is not None:
        stmt = stmt.where(DictionaryItem.code != except_code)
    return bool((await session.execute(stmt)).scalar_one())


_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
        "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
    }
)  # fmt: skip


def slug(name: str) -> str:
    """Код из названия: латиница и `_`, начинается с буквы, до 28 знаков (запас под суффикс уникальности)."""
    text = re.sub(r"[^a-z]+", "_", name.lower().translate(_TRANSLIT)).strip("_")
    text = text[:28].rstrip("_")
    return text if text else "item"


async def _free_code(session: AsyncSession, kind: str, base: str) -> str:
    taken = set(
        (
            await session.execute(
                select(DictionaryItem.code).where(DictionaryItem.kind == kind, DictionaryItem.code.like(f"{base}%"))
            )
        ).scalars()
    )
    if base not in taken:
        return base
    for suffix in "abcdefghijklmnopqrstuvwxyz":
        for second in ("", *"abcdefghijklmnopqrstuvwxyz"):
            code = f"{base}_{suffix}{second}"
            if code not in taken:
                return code
    raise conflict("code_exhausted", "Слишком много похожих названий — переименуйте значение.")


def _closed(spec: Spec) -> None:
    if spec.closed:
        raise conflict("dictionary_closed", "Этот список задаёт поведение системы: его можно только переименовать.")


async def create(session: AsyncSession, kind: str, data: DictionaryItemIn, *, actor_id: int) -> ItemOut:
    spec = _spec(kind)
    _closed(spec)
    if await _name_taken(session, kind, data.name.ru):
        raise conflict("name_taken", "Такое название уже есть в справочнике.")
    attrs = _clean_attrs(spec, data.attrs, {})
    position = (
        await session.execute(select(func.max(DictionaryItem.position)).where(DictionaryItem.kind == kind))
    ).scalar_one()
    now = clock.now()
    row = DictionaryItem(
        kind=kind,
        code=await _free_code(session, kind, slug(data.name.en or data.name.ru)),
        name_ru=data.name.ru,
        name_uz=data.name.uz,
        name_en=data.name.en,
        attrs=attrs,
        active=True,
        position=(position or 0) + POSITION_STEP,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    await journal.record(session, "dictionary.created", by=actor_id, comment=f"{kind}: {row.code}")
    return present(row, spec, used=False)


async def update(session: AsyncSession, kind: str, code: str, patch: DictionaryItemPatch, *, actor_id: int) -> ItemOut:
    spec = _spec(kind)
    row = await _get(session, kind, code, lock=True)
    if patch.active is not None and patch.active != row.active:
        _closed(spec)
        row.active = patch.active
    if patch.name is not None:
        if await _name_taken(session, kind, patch.name.ru, except_code=code):
            raise conflict("name_taken", "Такое название уже есть в справочнике.")
        row.name_ru, row.name_uz, row.name_en = patch.name.ru, patch.name.uz, patch.name.en
    if patch.attrs is not None:
        row.attrs = _clean_attrs(spec, patch.attrs, row.attrs)
    row.updated_at = clock.now()
    await session.flush()
    action = (
        "dictionary.updated" if patch.active is None else ("dictionary.shown" if row.active else "dictionary.hidden")
    )
    await journal.record(session, action, by=actor_id, comment=f"{kind}: {code}")
    return present(row, spec, used=code in await _used_codes(session, spec))


async def delete(session: AsyncSession, kind: str, code: str, *, actor_id: int) -> None:
    spec = _spec(kind)
    _closed(spec)
    row = await _get(session, kind, code, lock=True)
    if code in await _used_codes(session, spec):
        raise conflict("value_in_use", "Значение уже есть у писем — его можно только скрыть.")
    await session.delete(row)
    await session.flush()
    await journal.record(session, "dictionary.deleted", by=actor_id, comment=f"{kind}: {code}")


async def reorder(session: AsyncSession, kind: str, codes: list[str], *, actor_id: int) -> DictionaryItemList:
    spec = _spec(kind)
    rows = list(
        (await session.execute(select(DictionaryItem).where(DictionaryItem.kind == kind).with_for_update())).scalars()
    )
    by_code = {row.code: row for row in rows}
    if len(codes) != len(set(codes)) or set(codes) != set(by_code):
        raise invalid_fields("Нужен полный список значений справочника.", codes="must_list_all_codes")
    now = clock.now()
    for index, code in enumerate(codes):
        by_code[code].position = (index + 1) * POSITION_STEP
        by_code[code].updated_at = now
    await session.flush()
    await journal.record(session, "dictionary.reordered", by=actor_id, comment=kind)
    used = await _used_codes(session, spec)
    return DictionaryItemList(items=[present(by_code[code], spec, code in used) for code in codes])
