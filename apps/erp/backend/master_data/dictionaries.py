"""Справочники «Расчёта» общим ресурсом `/api/v1/dictionaries` (решение владельца 2026-11-11).

Тот же контракт, что у EDS и CRM (`docs/research/2026-11-11-reference-data/README.md` §C1): каталог видов с полями,
строки, добавить, изменить, порядок, удалить. Отличие ERP — код задаёт человек или файл (`USD`, `UZ`, `FCA`), а не
система из названия. Использованную строку удалить нельзя (`on_delete=PROTECT`), её отключают. Сброс кэша списков —
сигналом на запись модели (`master_data/signals.py`), как у прежних вьюсетов.

Список с источником (`Spec.source`; валюты — ЦБ, `master_data/cbu.py`): строка показывает источник и дату обновления,
правка поля источника руками запоминается (`manual_fields`), и источник его больше не перетирает. «Обновить» ставит
в очередь ту же задачу, что идёт по расписанию.
"""

import functools
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from django.db import IntegrityError, models, transaction
from django.db.models import ProtectedError

from .country_names import fill_missing_names
from .models import Bank, Country, Currency, DeliveryBasis, UnitOfMeasure

AttrType = Literal["boolean", "text", "decimal", "choice"]
CODE_MAX = 50


class DictionaryError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


@dataclass(frozen=True)
class Attr:
    key: str
    type: AttrType
    name: tuple[str, str, str]
    max_length: int = 255
    #: Значения `choice`: (значение, названия ru/uz/en)
    options: tuple[tuple[str, tuple[str, str, str]], ...] = ()
    #: Поле — ссылка (родитель категории, страна производителя): чтение и запись своими функциями;
    #: запись возвращает код ошибки поля или None.
    getter: Optional[Callable[[models.Model], Any]] = None
    setter: Optional[Callable[[models.Model, Any], Optional[str]]] = None


@dataclass(frozen=True)
class Spec:
    kind: str
    model: type[models.Model]
    name: tuple[str, str, str]
    attrs: tuple[Attr, ...] = ()
    code_upper: bool = True
    #: Код открытого источника, который ведёт список (`master_data/cbu.py`); None — список ведут руками.
    source: Optional[str] = None
    #: `given` — код задаёт человек или файл (`USD`); `generated` — код строки — её номер в базе, новой его выдаёт
    #: ERP (категории и производители каталога, план 3.8).
    codes: Literal["given", "generated"] = "given"
    related: tuple[str, ...] = ()


def _category_parent(row: models.Model) -> str:
    return str(row.parent_id) if row.parent_id else ""


def _set_category_parent(row: models.Model, value: Any) -> Optional[str]:
    """Родитель категории — код (номер) другой категории; пусто — корень. Своё поддерево родителем не бывает."""
    from catalog.models import Category

    text = "" if value is None else str(value).strip()
    if not text:
        row.parent = None
        return None
    if not text.isdigit():
        return "unknown"
    parent = Category.objects.filter(pk=int(text)).first()
    if parent is None:
        return "unknown"
    seen: set[int] = set()
    node: Optional[models.Model] = parent
    while node is not None and node.pk not in seen:
        if row.pk is not None and node.pk == row.pk:
            return "cycle"
        seen.add(node.pk)
        node = node.parent
    row.parent = parent
    return None


def _manufacturer_country(row: models.Model) -> str:
    return row.country.code if row.country_id else ""


def _set_manufacturer_country(row: models.Model, value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip().upper()
    if not text:
        row.country = None
        return None
    country = Country.objects.filter(code=text).first()
    if country is None:
        return "unknown"
    row.country = country
    return None


def _set_website(row: models.Model, value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    if text and not text.lower().startswith(("http://", "https://")):
        return "invalid_value"
    if len(text) > 200:
        return "too_long"
    row.website = text
    return None


def _catalog_specs() -> tuple["Spec", ...]:
    from catalog.constants import TrackingClass
    from catalog.models import Category, Manufacturer

    tracking_names = {
        TrackingClass.SERIAL: ("Серийный", "Seriyali", "Serial"),
        TrackingClass.LOT: ("Партия", "Partiya", "Lot"),
        TrackingClass.NONE: ("Только количество", "Faqat miqdor", "Quantity only"),
    }
    return (
        Spec(
            "categories",
            Category,
            ("Категории товаров", "Mahsulot toifalari", "Product categories"),
            attrs=(
                Attr(
                    "parent",
                    "text",
                    ("Родитель (код)", "Ota toifa (kodi)", "Parent (code)"),
                    20,
                    getter=_category_parent,
                    setter=_set_category_parent,
                ),
                Attr(
                    "tracking",
                    "choice",
                    ("Учёт единиц", "Birliklar hisobi", "Unit tracking"),
                    options=tuple((value, tracking_names[value]) for value in TrackingClass.values),
                ),
                Attr(
                    "requires_conformity_doc",
                    "boolean",
                    ("Нужен документ соответствия", "Muvofiqlik hujjati kerak", "Conformity document required"),
                ),
            ),
            codes="generated",
            related=("parent",),
        ),
        Spec(
            "manufacturers",
            Manufacturer,
            ("Бренды", "Brendlar", "Brands"),
            attrs=(
                Attr(
                    "country",
                    "text",
                    ("Страна (код)", "Mamlakat (kodi)", "Country (code)"),
                    3,
                    getter=_manufacturer_country,
                    setter=_set_manufacturer_country,
                ),
                Attr("website", "text", ("Сайт", "Sayt", "Website"), 200, setter=_set_website),
            ),
            codes="generated",
            related=("country",),
        ),
    )


def _sales_specs() -> tuple["Spec", ...]:
    from sales.models import DealCloseReason

    return (
        Spec(
            "request-close-reasons",
            DealCloseReason,
            ("Причины закрытия заявки", "Ariza yopilish sabablari", "Request close reasons"),
            attrs=(
                Attr(
                    "requires_comment",
                    "boolean",
                    ("Нужен комментарий", "Izoh majburiy", "Comment required"),
                ),
                Attr(
                    "allowed_after_quote_sent",
                    "boolean",
                    ("Допустима после отправки КП", "TT yuborilgandan keyin mumkin", "Allowed after quote sent"),
                ),
                Attr(
                    "hide_when_unsent",
                    "boolean",
                    (
                        "Скрывать из списков, если клиенту ничего не отправлено",
                        "Mijozga hech narsa yuborilmagan bo‘lsa, ro‘yxatlardan yashirish",
                        "Hide from lists if nothing was sent to the client",
                    ),
                ),
            ),
        ),
    )


SPECS: dict[str, Spec] = {
    spec.kind: spec
    for spec in (
        Spec(
            "countries",
            Country,
            ("Страны", "Mamlakatlar", "Countries"),
            attrs=(
                Attr("alpha3", "text", ("Код ISO alpha-3", "ISO alpha-3 kodi", "ISO alpha-3"), 3),
                Attr("iso_numeric", "text", ("Цифровой код ISO", "ISO raqamli kodi", "ISO numeric"), 3),
                Attr("vat_rate", "decimal", ("Ставка НДС, %", "QQS stavkasi, %", "VAT rate, %")),
            ),
        ),
        Spec(
            "currencies",
            Currency,
            ("Валюты", "Valyutalar", "Currencies"),
            attrs=(
                Attr("symbol", "text", ("Символ", "Belgi", "Symbol"), 10),
                Attr("iso_numeric", "text", ("Цифровой код ISO", "ISO raqamli kodi", "ISO numeric"), 3),
            ),
            source="cbu",
        ),
        Spec("units", UnitOfMeasure, ("Единицы измерения", "O‘lchov birliklari", "Units"), code_upper=False),
        # План 2.9: код — МФО (5 цифр), список — файлом ЦБ; SWIFT — для валютных счетов
        Spec(
            "banks",
            Bank,
            ("Банки", "Banklar", "Banks"),
            attrs=(Attr("swift", "text", ("SWIFT", "SWIFT", "SWIFT"), 11),),
            code_upper=False,
            source="cbu",
        ),
        Spec(
            "delivery-basis",
            DeliveryBasis,
            ("Базисы поставки", "Yetkazib berish bazislari", "Delivery terms"),
            attrs=(
                Attr("description", "text", ("Описание", "Tavsif", "Description"), 2000),
                Attr(
                    "seller_pays_freight", "boolean", ("Фрахт за продавцом", "Fraxt sotuvchida", "Seller pays freight")
                ),
                Attr(
                    "seller_pays_insurance",
                    "boolean",
                    ("Страховка за продавцом", "Sug‘urta sotuvchida", "Seller pays insurance"),
                ),
                Attr(
                    "seller_pays_import",
                    "boolean",
                    ("Ввоз за продавцом", "Import sotuvchida", "Seller pays import"),
                ),
                Attr(
                    "seller_pays_delivery",
                    "boolean",
                    ("Доставка за продавцом", "Yetkazish sotuvchida", "Seller pays delivery"),
                ),
            ),
        ),
    )
}


def _names(values: tuple[str, str, str]) -> dict[str, str]:
    return {"ru": values[0], "uz": values[1], "en": values[2]}


@functools.cache
def specs() -> dict[str, Spec]:
    """Все виды: справочники «Расчёта» и каталога. Виды каталога подключаются при первом обращении — модели каталога
    импортируются после загрузки приложений."""
    return {**SPECS, **{spec.kind: spec for spec in (*_catalog_specs(), *_sales_specs())}}


def _key(spec: Spec, row: models.Model) -> str:
    return str(row.pk) if spec.codes == "generated" else row.code


def _by_key(spec: Spec, code: str) -> dict[str, Any]:
    if spec.codes == "generated":
        return {"pk": int(code)} if str(code).isdigit() else {"pk": -1}
    return {"code": code}


def spec_of(kind: str) -> Spec:
    spec = specs().get(kind)
    if spec is None:
        raise DictionaryError(404, "NOT_FOUND", "Такого справочника нет.")
    return spec


#: Поля строки, которые ведёт источник: правка руками их «закрепляет» (`manual_fields`).
SOURCE_FIELDS = ("name", "name_uz", "name_en", "iso_numeric")


def _source_names(source: str) -> dict[str, str]:
    from .cbu import SOURCE, SOURCE_NAMES

    return dict(SOURCE_NAMES) if source == SOURCE else {"ru": source, "uz": source, "en": source}


def _catalog_source(spec: Spec) -> Optional[dict[str, Any]]:
    if spec.source is None:
        return None
    last = spec.model.objects.filter(source=spec.source).aggregate(last=models.Max("synced_at"))["last"]
    return {"name": _source_names(spec.source), "synced_at": last.isoformat() if last else None}


def catalog() -> dict[str, Any]:
    return {
        "items": [
            {
                "kind": spec.kind,
                "name": _names(spec.name),
                "closed": False,
                "codes": spec.codes,
                "attrs": [_attr_spec(a) for a in spec.attrs],
                "source": _catalog_source(spec),
            }
            for spec in specs().values()
        ]
    }


def _attr_spec(attr: Attr) -> dict[str, Any]:
    out: dict[str, Any] = {"key": attr.key, "type": attr.type, "name": _names(attr.name), "required": False}
    if attr.type == "choice":
        out["options"] = [{"value": value, "name": _names(names)} for value, names in attr.options]
    return out


def _attr_out(attr: Attr, value: Any) -> Any:
    if attr.type == "decimal":
        return None if value is None else str(value)
    if attr.type in ("text", "choice"):
        return value or ""
    return bool(value)


def present(spec: Spec, row: models.Model) -> dict[str, Any]:
    return {
        "code": _key(spec, row),
        "name": {"ru": row.name, "uz": row.name_uz, "en": row.name_en},
        "attrs": {a.key: _attr_out(a, a.getter(row) if a.getter else getattr(row, a.key)) for a in spec.attrs},
        "active": row.is_active,
        "position": row.sort_order,
        "used": None,
        "source": _row_source(row),
    }


def _row_source(row: models.Model) -> Optional[dict[str, Any]]:
    source = getattr(row, "source", "")
    if not source:
        return None
    synced = row.synced_at
    return {
        "name": _source_names(source),
        "synced_at": synced.isoformat() if synced else None,
        "missing": not row.in_source,
    }


def items(kind: str, *, include_hidden: bool) -> dict[str, Any]:
    spec = spec_of(kind)
    rows = spec.model.objects.select_related(*spec.related).order_by("sort_order", "name")
    if not include_hidden:
        rows = rows.filter(is_active=True)
    return {"items": [present(spec, row) for row in rows]}


def _invalid(fields: dict[str, str], message: str = "Проверьте поля значения.") -> DictionaryError:
    return DictionaryError(422, "VALIDATION_FAILED", message, {"fields": fields})


def _apply(spec: Spec, row: models.Model, data: dict[str, Any]) -> None:
    errors: dict[str, str] = {}
    name = data.get("name")
    if name is not None:
        if not isinstance(name, dict):
            raise _invalid({"name": "invalid"})
        ru = str(name.get("ru") or "").strip()
        if "ru" in name and not ru:
            errors["name.ru"] = "required"
        for lang, field in (("ru", "name"), ("uz", "name_uz"), ("en", "name_en")):
            if lang in name:
                text = str(name.get(lang) or "").strip()
                if len(text) > 255:
                    errors[f"name.{lang}"] = "too_long"
                setattr(row, field, text)
    attrs = data.get("attrs") or {}
    known = {a.key: a for a in spec.attrs}
    for key, value in attrs.items():
        attr = known.get(key)
        if attr is None:
            errors[f"attrs.{key}"] = "unknown_attr"
            continue
        if attr.setter is not None:
            problem = attr.setter(row, value)
            if problem:
                errors[f"attrs.{key}"] = problem
        elif attr.type == "choice":
            if value not in {option for option, _names_ in attr.options}:
                errors[f"attrs.{key}"] = "invalid_value"
                continue
            setattr(row, key, value)
        elif attr.type == "boolean":
            if not isinstance(value, bool):
                errors[f"attrs.{key}"] = "invalid_value"
                continue
            setattr(row, key, value)
        elif attr.type == "decimal":
            if value in (None, ""):
                setattr(row, key, None)
                continue
            try:
                setattr(row, key, Decimal(str(value).replace(",", ".")))
            except InvalidOperation:
                errors[f"attrs.{key}"] = "invalid_value"
        else:
            text = "" if value is None else str(value).strip()
            if len(text) > attr.max_length:
                errors[f"attrs.{key}"] = "too_long"
                continue
            setattr(row, key, text)
    if "active" in data:
        row.is_active = bool(data["active"])
    if errors:
        raise _invalid(errors)


def _code(spec: Spec, raw: Any) -> str:
    code = str(raw or "").strip()
    code = code.upper() if spec.code_upper else code
    if not code or len(code) > CODE_MAX or any(ch.isspace() for ch in code):
        raise _invalid({"code": "required" if not code else "invalid"})
    return code


@transaction.atomic
def create(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    spec = spec_of(kind)
    if spec.codes == "generated":
        return _create_generated(spec, data)
    code = _code(spec, data.get("code"))
    if spec.model.objects.filter(code=code).exists():
        raise DictionaryError(409, "CONFLICT", "Такой код уже есть.", {"reason": "code_taken", "fields": ["code"]})
    row = spec.model(code=code)
    if not str((data.get("name") or {}).get("ru") or "").strip():
        raise _invalid({"name.ru": "required"})
    _apply(spec, row, data)
    if spec.model is Country:
        row.alpha2 = code[:2]
        # Названия, которые не ввели, — из CLDR: страна по коду сразу видна на трёх языках.
        fill_missing_names(row)
    last = spec.model.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
    row.sort_order = last + 10
    try:
        row.save()
    except IntegrityError as exc:
        raise DictionaryError(409, "CONFLICT", "Такой код уже есть.", {"reason": "code_taken"}) from exc
    return present(spec, row)


def _create_generated(spec: Spec, data: dict[str, Any]) -> dict[str, Any]:
    """Новая строка списка, где код выдаёт ERP (категория, производитель): код — номер строки в базе."""
    row = spec.model()
    if not str((data.get("name") or {}).get("ru") or "").strip():
        raise _invalid({"name.ru": "required"})
    _apply(spec, row, data)
    last = spec.model.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
    row.sort_order = last + 10
    _save_named(row)
    return present(spec, row)


def _save_named(row: models.Model) -> None:
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError as exc:
        raise DictionaryError(
            409, "CONFLICT", "Такое название уже есть.", {"reason": "name_taken", "fields": ["name"]}
        ) from exc


def _get(spec: Spec, code: str) -> models.Model:
    row = spec.model.objects.select_for_update().filter(**_by_key(spec, code)).first()
    if row is None:
        raise DictionaryError(404, "NOT_FOUND", "Такого значения в справочнике нет.")
    return row


@transaction.atomic
def update(kind: str, code: str, data: dict[str, Any]) -> dict[str, Any]:
    spec = spec_of(kind)
    row = _get(spec, code)
    before = {f: getattr(row, f, None) for f in SOURCE_FIELDS}
    _apply(spec, row, data)
    if getattr(row, "source", ""):
        touched = {f for f, value in before.items() if getattr(row, f, None) != value}
        row.manual_fields = sorted(set(row.manual_fields or []) | touched)
    _save_named(row)
    return present(spec, row)


def sync(kind: str) -> dict[str, Any]:
    """«Обновить» список с источником: ставит в очередь задачу расписания (валюты и курсы ЦБ; банки — файл ЦБ)."""
    spec = spec_of(kind)
    if spec.source is None:
        raise DictionaryError(404, "NOT_FOUND", "У этого справочника нет источника.")
    from .tasks import refresh_bank_codes, refresh_exchange_rates

    (refresh_bank_codes if spec.model is Bank else refresh_exchange_rates).delay()
    return {"queued": True}


@transaction.atomic
def reorder(kind: str, codes: list[str]) -> dict[str, Any]:
    spec = spec_of(kind)
    rows = {_key(spec, row): row for row in spec.model.objects.select_for_update()}
    if sorted(codes) != sorted(rows):
        raise _invalid({"codes": "must_list_all"}, "Перечислите все коды справочника.")
    for index, code in enumerate(codes):
        row = rows[code]
        if row.sort_order != (index + 1) * 10:
            row.sort_order = (index + 1) * 10
            row.save(update_fields=["sort_order"])
    return items(kind, include_hidden=True)


@transaction.atomic
def delete(kind: str, code: str) -> None:
    spec = spec_of(kind)
    row = _get(spec, code)
    try:
        with transaction.atomic():
            row.delete()
    except ProtectedError as exc:
        raise DictionaryError(
            409, "CONFLICT", "Значение уже используется — его можно только скрыть.", {"reason": "value_in_use"}
        ) from exc
