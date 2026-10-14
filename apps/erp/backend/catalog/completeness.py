"""Полнота карточки товара: готовность ВЫЧИСЛЯЕТСЯ, а не назначается кнопкой.

Эталон — Akeneo PIM: карточка готова к каналу не тогда, когда кто-то нажал «опубликовать», а
когда заполнены обязательные для этого канала атрибуты; процент полноты виден пользователю и
сам объясняет, что делать дальше. Pimcore выражает то же через workflow с условиями перехода.

У нас это заменяет ручное благословение платформы: до волны A опубликовать карточку мог ТОЛЬКО
платформенный оператор (`bulk_publish` под `IsPlatformAdmin`) — продавец не мог выпустить в
каталог даже собственный товар. Теперь публикует владелец, а роль «проверяющего» играет
детерминированный порог.

Набор обязательного зависит от домена: у ж/д запчасти без ГОСТ/чертежа или артикула нет
идентичности, а у услуги их не бывает вовсе.
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

REQUIREMENTS_BY_DOMAIN: dict[str, tuple] = {
    # Ж/д техника: идентичность и ТН ВЭД — то, без чего деталь не подобрать.
    "RAILWAY_MACHINERY": (_NAME, _UOM, _CATEGORY, _IDENTITY, _HS),
    # Общие товары: идентичность желательна, но не обязательна — многое продаётся по описанию.
    "GENERAL_GOODS": (_NAME, _UOM, _CATEGORY, _HS),
    # Услуги: ни артикула, ни ТН ВЭД не бывает.
    "SERVICES": (_NAME, _UOM, _CATEGORY),
}
#: Домен не указан (карточка-кандидат в самом начале пути) — спрашиваем общий минимум.
DEFAULT_REQUIREMENTS = (_NAME, _UOM, _CATEGORY, _HS)


def requirements_for(product) -> tuple:
    domain_code = getattr(getattr(product, "domain_type", None), "code", None)
    return REQUIREMENTS_BY_DOMAIN.get(domain_code, DEFAULT_REQUIREMENTS)


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


def completeness(product, ctx: CompletenessContext | None = None) -> dict:
    """`{percent, missing: [{code, label}], is_publishable}` для одной карточки.

    `missing` — главное поле: процент мотивирует, а список говорит, ЧТО именно сделать.

    `ctx` передаёт список: один контекст на страницу вместо справочных запросов на строку.
    Без него (одиночная карточка: детальный сериализатор, публикация) контекст строится сам.
    """
    ctx = ctx if ctx is not None else CompletenessContext([product])
    requirements = requirements_for(product)
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
