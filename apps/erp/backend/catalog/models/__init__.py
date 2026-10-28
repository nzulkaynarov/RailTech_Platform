"""models package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .hs_code import HSCode
from .lookups import DomainType, ProductStatus, StockStatus
from .offers import SupplierOffer
from .products import Product, ProductDocument, ProductImage
from .requests import CategoryRequest
from .taxonomy import Category, Manufacturer
from .tech_docs import TechDocument

from .brigades import Brigade  # isort:skip — после HSCode: master_data.models импортирует его отсюда

__all__ = [
    "Brigade",
    "Category",
    "CategoryRequest",
    "DomainType",
    "HSCode",
    "Manufacturer",
    "Product",
    "ProductDocument",
    "ProductImage",
    "ProductStatus",
    "StockStatus",
    "SupplierOffer",
    "TechDocument",
]
