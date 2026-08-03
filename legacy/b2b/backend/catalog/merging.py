"""Слияние карточек-дублей: две записи об одной детали становятся одной.

Дубли неизбежны по построению: у каждого продавца своя карточка (гибрид Grainger), позиция
приходит из заявок под разными именами («Подшипник буксовый 30-232726Е2М» и «Подшипник 232726
(буксовый узел)»), а точный ключ (артикул или ГОСТ) есть не всегда. Автоматически такие
карточки не склеиваются — «подшипник буксовый» есть у каждого второго, и ложное слияние стоит
дороже дубля.

Эталон: Akeneo и Pimcore дают ручное слияние с выбором «выжившей» записи; у Salesforce и
HubSpot дедупликация контактов устроена так же — система ПРЕДЛАГАЕТ, человек решает.

Правила слияния:

* **Выжившая карточка сохраняет свою идентичность** (SKU, номер, статус) — на неё уже могут
  ссылаться строки КП и офферы.
* **Пустые поля выжившей дозаполняются** из поглощаемой: слияние обязано ДОБАВЛЯТЬ знание,
  а не терять его.
* **Спрос суммируется** — иначе очередь наполнения потеряет накопленную статистику.
* **Ссылки переезжают**: офферы и строки КП начинают указывать на выжившую.
* **Поглощённая уходит в АРХИВ, а не удаляется** — на неё могут ссылаться исторические
  документы, а удаление истории запрещено (то же правило, что у выпущенных документов).
"""

from __future__ import annotations

from django.db import transaction

#: Поля, которые дозаполняются в выжившей карточке из поглощаемой (только если пусты).
MERGEABLE_TEXT_FIELDS = (
    "description",
    "manufacturer_part_number",
    "gost_drawing",
    "hs_code",
)
MERGEABLE_FK_FIELDS = ("category", "uom", "brand", "domain_type", "source_deal")


def can_merge(user, product) -> bool:
    from catalog.publishing import can_manage

    return can_manage(user, product)


@transaction.atomic
def merge_products(survivor, duplicate, actor) -> tuple[object | None, str | None]:
    """Слить `duplicate` в `survivor`. Возвращает `(survivor, error_code)`."""
    from catalog.models import ProductStatus, SupplierOffer
    from crm.models import QuoteItem

    if survivor.pk == duplicate.pk:
        return None, "MERGE_SAME_PRODUCT"
    if not (can_merge(actor, survivor) and can_merge(actor, duplicate)):
        return None, "PRODUCT_NOT_YOURS"
    # Платформа сводит карточки РАЗНЫХ продавцов в мастер-запись; продавец — только свои.
    same_owner = survivor.owner_company_id == duplicate.owner_company_id
    if not same_owner and not getattr(actor, "is_platform_admin", False):
        return None, "MERGE_CROSS_COMPANY_FORBIDDEN"

    updated: list[str] = []
    for field in MERGEABLE_TEXT_FIELDS:
        if not (getattr(survivor, field, "") or "").strip() and (getattr(duplicate, field, "") or "").strip():
            setattr(survivor, field, getattr(duplicate, field))
            updated.append(field)
    for field in MERGEABLE_FK_FIELDS:
        if getattr(survivor, f"{field}_id", None) is None and getattr(duplicate, f"{field}_id", None) is not None:
            setattr(survivor, f"{field}_id", getattr(duplicate, f"{field}_id"))
            updated.append(field)

    # Спрос — накопленная статистика очереди наполнения, её нельзя терять при слиянии.
    survivor.demand_count = (survivor.demand_count or 0) + (duplicate.demand_count or 0)
    updated.append("demand_count")
    last_seen = max(filter(None, [survivor.last_requested_at, duplicate.last_requested_at]), default=None)
    if last_seen:
        survivor.last_requested_at = last_seen
        updated.append("last_requested_at")
    survivor.save(update_fields=list(dict.fromkeys(updated)) + ["updated_at"])

    # Ссылки переезжают: иначе оффер и строка КП остались бы висеть на архивной карточке.
    SupplierOffer.objects.filter(product=duplicate).update(product=survivor)
    QuoteItem.objects.filter(product=duplicate).update(product=survivor)
    duplicate.equipment_groups.through.objects.filter(product_id=duplicate.pk).delete()

    archived = ProductStatus.objects.filter(code="ARCHIVED").first()
    if archived is None:
        return None, "PRODUCT_STATUS_MISSING"
    duplicate.status = archived
    duplicate.save(update_fields=["status", "updated_at"])
    return survivor, None
