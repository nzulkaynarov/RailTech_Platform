"""Полнота карточки товара: готовность ВЫЧИСЛЯЕТСЯ, а не назначается кнопкой.

Эталон — Akeneo PIM: карточка готова к каналу не тогда, когда кто-то нажал «опубликовать», а
когда заполнены обязательные для этого канала атрибуты; процент полноты виден пользователю и
сам объясняет, что делать дальше. Pimcore выражает то же через workflow с условиями перехода.

У нас это заменяет ручное благословение платформы: до волны A опубликовать карточку мог ТОЛЬКО
платформенный оператор (`bulk_publish` под `IsPlatformAdmin`) — продавец не мог выпустить в
каталог даже собственный товар. Теперь публикует владелец, а роль «проверяющего» играет
детерминированный порог.

Набор обязательного зависит от вида и видимости (M1-ERP-07 — порог публикации опубликованного
слоя): у товара — ТН ВЭД, у услуги — политика исполнения (и единица времени для «по времени»),
у видимости «в кабинете» — цена для клиента; у всех — вид, имя, единица, категория и описание
или характеристики.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

#: Размер пачки для догрузки m2m в `summarize_completeness`. Держит `IN (...)` в разумных
#: рамках на импорте в десятки тысяч строк, оставляя цену «запросов на карточку» нулевой.
COMPLETENESS_BATCH = 500


def hs_digits(product) -> str:
    """Нормализация кода карточки к ключу справочника — только цифры (как в `validate_hs_code`)."""
    return "".join(ch for ch in (product.hs_code or "") if ch.isdigit())


#: Домен → список обязательных требований. Каждое требование: (код, подпись, проверка).
#: Код нужен интерфейсу, чтобы сказать «не хватает: категория, ТН ВЭД» на языке пользователя.
#: Проверка получает ВТОРЫМ аргументом `CompletenessContext` — справочные факты, общие для всей
#: страницы списка (см. ниже, почему это не деталь реализации, а часть контракта).
_NAME = ("name", _("Наименование"), lambda p, ctx: bool((p.name or "").strip()))
_UOM = ("uom", _("Единица измерения"), lambda p, ctx: p.uom_id is not None)
_CATEGORY = ("category", _("Категория"), lambda p, ctx: p.category_id is not None)


def _hs_is_current(product, ctx) -> bool:
    """Код заполнен И не выведен из редакции классификатора.

    Паттерн SAP-переклассификации: после автосинка закрытый код перестаёт удовлетворять
    требованию полноты, карточка возвращается в очередь наполнения с конкретной подсказкой —
    а не тихо наследует мёртвый код в новые КП. При пустом справочнике любой код считается
    действующим (работа без данных не блокируется).

    Вердикт берётся из ПАКЕТНО загруженного контекста, а не из `validate_hs_code` на строку:
    последний стоил два запроса (`exists()` + `filter(code=...)`) на КАЖДУЮ карточку списка.
    """
    if not hs_digits(product):
        return False
    if not ctx.hs_classifier_populated:
        return True
    return hs_digits(product) in ctx.current_hs_codes


_HS = ("hs_code", _("Код ТН ВЭД (действующий)"), _hs_is_current)
_IDENTITY = (
    "identity",
    _("Артикул производителя или ГОСТ/чертёж"),
    lambda p, ctx: bool((p.manufacturer_part_number or "").strip() or (p.gost_drawing or "").strip()),
)

# ── Порог публикации опубликованного слоя (M1-ERP-07) ───────────────────────────
#: Вид карточки — товар или услуга (справочник `domain_type`).
_KIND = ("kind", _("Вид: товар или услуга"), lambda p, ctx: p.domain_type_id is not None)


def _has_content(product, ctx) -> bool:
    """Клиенту есть что прочитать: описание или хотя бы одна заполненная характеристика."""
    if (product.description or "").strip():
        return True
    specs = product.specifications if isinstance(product.specifications, dict) else {}
    return any(str(value).strip() for value in specs.values() if value is not None)


_CONTENT = ("content", _("Описание или характеристики"), _has_content)
#: Услуга без политики исполнения не говорит клиенту, как её закажут и выставят (Odoo invoice policy).
_POLICY = ("fulfillment_policy", _("Политика исполнения услуги"), lambda p, ctx: bool(p.fulfillment_policy))


def _time_unit_ok(product, ctx) -> bool:
    """Услуга «по времени» считается в часах или сутках — иначе цена за единицу бессмысленна."""
    from catalog.models import TIME_UNIT_CODES, FulfillmentPolicy

    if product.fulfillment_policy != FulfillmentPolicy.TIME:
        return True
    return product.uom_id is not None and product.uom.code in TIME_UNIT_CODES


_TIME_UNIT = ("time_unit", _("Единица времени для услуги «по времени» (час, сутки)"), _time_unit_ok)
#: Видимость «в кабинете» обещает клиенту цену — без цены и валюты публиковать нечего.
_LIST_PRICE = (
    "list_price",
    _("Цена для клиента и валюта"),
    lambda p, ctx: p.list_price is not None and p.list_price_currency_id is not None,
)

REQUIREMENTS_BY_DOMAIN: dict[str, tuple] = {
    # Товары: вид, наименование, ед. изм., категория, описание/характеристики, ТН ВЭД.
    "GENERAL_GOODS": (_NAME, _KIND, _UOM, _CATEGORY, _CONTENT, _HS),
    # Услуги: ни артикула, ни ТН ВЭД не бывает — зато нужна политика исполнения.
    "SERVICES": (_NAME, _KIND, _UOM, _CATEGORY, _CONTENT, _POLICY, _TIME_UNIT),
}
#: Домен не указан (карточка-кандидат в самом начале пути) — спрашиваем общий минимум и сам вид.
DEFAULT_REQUIREMENTS = (_NAME, _KIND, _UOM, _CATEGORY, _CONTENT, _HS)


def requirements_for(product, visibility: str | None = None) -> tuple:
    """Требования порога публикации: по виду карточки плюс по видимости.

    `visibility` — та, с которой карточку собираются публиковать (по умолчанию — её текущая):
    «в кабинете» добавляет цену для клиента.
    """
    from catalog.models import CatalogVisibility

    domain_code = getattr(getattr(product, "domain_type", None), "code", None)
    requirements = REQUIREMENTS_BY_DOMAIN.get(domain_code, DEFAULT_REQUIREMENTS)
    target = visibility or getattr(product, "visibility", None)
    if target == CatalogVisibility.CABINET:
        requirements = (*requirements, _LIST_PRICE)
    return requirements


class CompletenessContext:
    """Справочные факты, ОБЩИЕ для всей пачки карточек, — считаются один раз на пачку.

    Зачем: полнота считается для КАЖДОЙ строки списка, а её требования опираются на
    справочник ТН ВЭД.
    """

    def __init__(self, products):
        self._hs_populated = None
        self.current_hs_codes: frozenset[str] = frozenset()

        codes = {digits for digits in (hs_digits(product) for product in products) if digits}
        if not codes:
            return
        from django.utils import timezone

        from master_data.models import HSCode

        today = timezone.localdate()
        rows = list(HSCode.objects.filter(code__in=codes).values_list("code", "valid_until"))
        self.current_hs_codes = frozenset(
            code for code, valid_until in rows if not (valid_until and valid_until < today)
        )
        if rows:
            # Хоть один код страницы нашёлся — значит справочник наполнен, отдельный
            # `exists()` спрашивать не о чем.
            self._hs_populated = True

    @property
    def hs_classifier_populated(self) -> bool:
        if self._hs_populated is None:
            from master_data.models import HSCode

            self._hs_populated = HSCode.objects.exists()
        return self._hs_populated


def completeness(product, ctx: CompletenessContext | None = None, *, visibility: str | None = None) -> dict:
    """`{percent, missing: [{code, label}], is_publishable}` для одной карточки.

    `missing` — главное поле: процент мотивирует, а список говорит, ЧТО именно сделать.

    `ctx` передаёт список: один контекст на страницу вместо справочных запросов на строку.
    Без него (одиночная карточка: детальный сериализатор, публикация) контекст строится сам.
    """
    ctx = ctx if ctx is not None else CompletenessContext([product])
    requirements = requirements_for(product, visibility)
    missing = [{"code": code, "label": str(label)} for code, label, check in requirements if not check(product, ctx)]
    filled = len(requirements) - len(missing)
    percent = round(filled * 100 / len(requirements)) if requirements else 100
    return {"percent": percent, "missing": missing, "is_publishable": not missing}


def summarize_completeness(products) -> dict:
    """Сводка по ПАЧКЕ карточек: `{unpublishable, missing_breakdown}`.

    Зачем отдельная функция: массовая загрузка прайс-листа создаёт тысячи черновиков, и
    единственный честный ответ продавцу — «столько-то из них опубликовать нельзя, и вот чего
    им не хватает». Считать это надо ТЕМИ ЖЕ правилами, что и порог публикации, иначе отчёт
    начнёт расходиться с кнопкой «Опубликовать» (Akeneo показывает полноту тем же движком,
    которым закрывает канал).

    Цена в запросах не растёт со строками: один `CompletenessContext` на всю пачку +
    пакетная догрузка `equipment_groups` вместо `.exists()` на карточку.
    """
    products = [product for product in products if product is not None]
    if not products:
        return {"unpublishable": 0, "missing_breakdown": []}

    ctx = CompletenessContext(products)
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    unpublishable = 0
    for product in products:
        report = completeness(product, ctx)
        if report["is_publishable"]:
            continue
        unpublishable += 1
        for item in report["missing"]:
            counts[item["code"]] = counts.get(item["code"], 0) + 1
            labels[item["code"]] = item["label"]

    breakdown = [{"code": code, "label": labels[code], "count": count} for code, count in counts.items()]
    breakdown.sort(key=lambda item: (-item["count"], item["code"]))
    return {"unpublishable": unpublishable, "missing_breakdown": breakdown}
