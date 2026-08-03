"""Покрытие каталога: какая доля строк КП опирается на карточку товара.

Одна цифра, которая показывает, работает ли направление «Номенклатура». На старте волны A она
равнялась **8%** — 90 из 98 строк КП шли мимо каталога, то есть каждая позиция описывалась
заново и знание умирало вместе с КП.

Почему именно строки КП, а не число карточек: каталог из тысячи неиспользуемых карточек ничего
не стоит, а сотня востребованных экономит продавцу день работы в неделю. Эталон меряет так же —
у Ariba ключевой показатель enablement это доля закупок, прошедших ПО каталогу (catalog spend),
а не размер каталога.
"""

from __future__ import annotations

from django.db.models import Count, Q


def catalog_coverage(seller_company=None) -> dict:
    """`{lines_total, lines_with_product, percent, candidates_pending}`.

    Без компании — платформенный срез (плоскость оператора); с компанией — срез продавца.
    """
    from catalog.models import Product
    from crm.models import QuoteItem

    lines = QuoteItem.objects.billable() if hasattr(QuoteItem.objects, "billable") else QuoteItem.objects.all()
    if seller_company is not None:
        lines = lines.filter(quote__seller_company=seller_company)

    totals = lines.aggregate(
        total=Count("id"),
        with_product=Count("id", filter=Q(product__isnull=False)),
    )
    total = totals["total"] or 0
    with_product = totals["with_product"] or 0

    candidates = Product.objects.filter(status__code="DRAFT")
    if seller_company is not None:
        candidates = candidates.filter(owner_company=seller_company)

    return {
        "lines_total": total,
        "lines_with_product": with_product,
        "percent": round(with_product * 100 / total) if total else 0,
        "candidates_pending": candidates.count(),
    }
