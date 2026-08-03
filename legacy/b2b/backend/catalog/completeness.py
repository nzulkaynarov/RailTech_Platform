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

#: Домен → список обязательных требований. Каждое требование: (код, подпись, проверка).
#: Код нужен интерфейсу, чтобы сказать «не хватает: категория, ТН ВЭД» на языке пользователя.
_NAME = ("name", _("Наименование"), lambda p: bool((p.name or "").strip()))
_UOM = ("uom", _("Единица измерения"), lambda p: p.uom_id is not None)
_CATEGORY = ("category", _("Категория"), lambda p: p.category_id is not None)
_HS = ("hs_code", _("Код ТН ВЭД"), lambda p: bool((p.hs_code or "").strip()))
_IDENTITY = (
    "identity",
    _("Артикул производителя или ГОСТ/чертёж"),
    lambda p: bool((p.manufacturer_part_number or "").strip() or (p.gost_drawing or "").strip()),
)
_EQUIPMENT = (
    "equipment_groups",
    _("Группа оборудования"),
    lambda p: p.pk is not None and p.equipment_groups.exists(),
)

REQUIREMENTS_BY_DOMAIN: dict[str, tuple] = {
    # Ж/д техника: идентичность и применимость к оборудованию — то, без чего деталь не подобрать.
    "RAILWAY_MACHINERY": (_NAME, _UOM, _CATEGORY, _IDENTITY, _EQUIPMENT, _HS),
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


def completeness(product) -> dict:
    """`{percent, missing: [{code, label}], is_publishable}` для одной карточки.

    `missing` — главное поле: процент мотивирует, а список говорит, ЧТО именно сделать.
    """
    requirements = requirements_for(product)
    missing = [{"code": code, "label": str(label)} for code, label, check in requirements if not check(product)]
    filled = len(requirements) - len(missing)
    percent = round(filled * 100 / len(requirements)) if requirements else 100
    return {"percent": percent, "missing": missing, "is_publishable": not missing}
