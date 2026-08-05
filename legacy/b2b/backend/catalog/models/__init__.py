"""models package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .lookups import DomainType, ProductStatus, StockStatus
from .offers import SupplierOffer
from .products import Product, ProductDocument, ProductImage
from .requests import CategoryRequest
from .taxonomy import Category, EquipmentGroup, Manufacturer

__all__ = [
    "Category",
    "CategoryRequest",
    "DomainType",
    "EquipmentGroup",
    "Manufacturer",
    "Product",
    "ProductDocument",
    "ProductImage",
    "ProductStatus",
    "StockStatus",
    "SupplierOffer",
]
