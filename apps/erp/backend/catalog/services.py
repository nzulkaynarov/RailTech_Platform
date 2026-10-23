"""
Catalog business logic — single source of truth.

Called from both Django Unfold actions and DRF endpoints.
See ADR-0001 and CONVENTIONS.md IRON RULE 8.
"""

from typing import List, Tuple

from django.db.models import QuerySet

from .models import Product, ProductStatus


def publish_products(products: QuerySet[Product]) -> Tuple[int, List[str]]:
    """
    Publish products: set status to PUBLISHED.

    Only publishes DRAFT products. Skips products without domain_type.

    Returns:
        (count_published, list_of_skipped_product_names)
        If validation fails (no PUBLISHED status), returns (0, [error]).
    """
    published_status = ProductStatus.objects.filter(code="PUBLISHED").first()
    if not published_status:
        return 0, ["ProductStatus 'PUBLISHED' not found in master data"]

    # Only publish DRAFT products
    draft_products = products.filter(status__code="DRAFT")

    skipped = list(draft_products.filter(domain_type__isnull=True).values_list("name", flat=True))

    publishable = draft_products.exclude(domain_type__isnull=True)
    updated = publishable.update(status=published_status)
    return updated, skipped


def find_or_create_manufacturer(name: str):
    """Бренд по имени без дублей (`iexact`) — ЕДИНЫЙ нормализатор формы и Excel-импорта (N1).

    До N1 бренд можно было завести только побочным эффектом импорта (свободный текст из
    файла), а селект в форме карточки был вечно пуст. Паттерн Odoo «create on the fly» /
    Amazon brand: бренд — нормализуемый ввод продавца, не закрытый справочник. Пустое имя →
    None (бренд снят).
    """
    from .models import Manufacturer

    cleaned = (name or "").strip()
    if not cleaned:
        return None
    existing = Manufacturer.objects.filter(name__iexact=cleaned).first()
    return existing or Manufacturer.objects.create(name=cleaned)


def offer_validity_error(valid_from, valid_until) -> str | None:
    """Код ошибки окна действия цены (`None` — окно корректно).

    Эталон — `product.supplierinfo` в Odoo (Validity Start/End) и info-record SAP: у цены
    поставщика есть срок, и «действует до» не может стоять раньше «действует с». Открытые
    границы законны: пустое «с» — «действует уже сейчас», пустое «до» — «бессрочно».

    Rule 8: правило живёт здесь, сериализатор его только вызывает.
    """
    if valid_from and valid_until and valid_until < valid_from:
        return "OFFER_VALIDITY_RANGE_INVALID"
    return None


def log_hs_code_change(product, old_code: str, actor, origin: str) -> None:
    """Журнал присвоений кода ТН ВЭД (T2, паттерн Avalara: у классификации есть источник).

    `origin` — откуда пришёл код: manual (поле в форме) / ai (выбор модели из кандидатов) /
    quote_line (перенос из строки КП) / sync (закрыт автосинком). Позволяет спорить с
    классификацией по существу: «кто так решил» перестаёт быть вопросом.
    """
    from crm.models import ActivityLog

    new_code = (product.hs_code or "").strip()
    if (old_code or "").strip() == new_code:
        return
    ActivityLog.objects.create(
        action="Код ТН ВЭД изменён",
        detail=f"Товар «{product.name[:60]}»: {old_code or '—'} → {new_code or '—'}",
        event_code="product.hs_code_changed",
        event_params={
            "product_id": product.pk,
            "name": product.name[:120],
            "from_code": old_code or "",
            "to_code": new_code,
            "origin": origin,
        },
        user=actor if getattr(actor, "is_authenticated", False) else None,
        level="INFO",
        company_id=product.owner_company_id,
    )
