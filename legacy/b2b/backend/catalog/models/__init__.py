"""models package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .lookups import DomainType, ProductStatus, StockStatus
from .offers import SupplierOffer
from .products import Product, ProductDocument, ProductImage
from .taxonomy import Category, EquipmentGroup

__all__ = [
    "Category",
    "DomainType",
    "EquipmentGroup",
    "Product",
    "ProductDocument",
    "ProductImage",
    "ProductStatus",
    "StockStatus",
    "SupplierOffer",
]
