"""views package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .lookups import (
    LIST_CACHE_TTL,
    LOOKUP_CACHE_TTL,
    CategoryViewSet,
    DomainTypeViewSet,
    EquipmentGroupViewSet,
    ManufacturerViewSet,
    ProductStatusViewSet,
    StockStatusViewSet,
)
from .ai import ProductEnrichView
from .offers import SupplierOfferViewSet
from .products import ProductViewSet

__all__ = [
    "CategoryViewSet",
    "DomainTypeViewSet",
    "EquipmentGroupViewSet",
    "LIST_CACHE_TTL",
    "LOOKUP_CACHE_TTL",
    "ManufacturerViewSet",
    "ProductEnrichView",
    "ProductStatusViewSet",
    "ProductViewSet",
    "StockStatusViewSet",
    "SupplierOfferViewSet",
]
