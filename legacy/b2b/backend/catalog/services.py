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
