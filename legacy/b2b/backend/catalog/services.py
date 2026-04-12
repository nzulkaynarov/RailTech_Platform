"""
Catalog business logic — single source of truth.

Called from both Django Unfold actions and DRF endpoints.
See ADR-0001 and CLAUDE.md IRON RULE 8.
"""
from typing import List, Tuple

from django.db.models import QuerySet

from .models import Product, ProductStatus


def publish_products(products: QuerySet[Product]) -> Tuple[int, List[str]]:
    """
    Publish products: set status to PUBLISHED.

    Validation: every product must have a domain_type assigned.

    Returns:
        (count_published, list_of_skipped_product_names)
        If validation fails (no PUBLISHED status / products without domain),
        returns (0, [error_or_skipped_names]).
    """
    published_status = ProductStatus.objects.filter(code='PUBLISHED').first()
    if not published_status:
        return 0, ["ProductStatus 'PUBLISHED' not found in master data"]

    skipped = list(
        products.filter(domain_type__isnull=True).values_list('name', flat=True)
    )
    if skipped:
        return 0, skipped

    updated = products.update(status=published_status)
    return updated, []
