"""models package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .hs_code import HSCode
from .lookups import DomainType, ProductStatus, StockStatus
from .offers import SupplierOffer
from .products import Product, ProductDocument, ProductImage
from .proposals import ProductFieldProposal
from .requests import CategoryRequest
from .taxonomy import Category, Manufacturer
from .tech_docs import CONFORMITY_KIND_CODES, DocumentKind, TechDocument

from .brigades import Brigade  # isort:skip — после HSCode: master_data.models импортирует его отсюда

__all__ = [
    "Brigade",
    "Category",
    "CategoryRequest",
    "CONFORMITY_KIND_CODES",
    "DocumentKind",
    "DomainType",
    "HSCode",
    "Manufacturer",
    "Product",
    "ProductDocument",
    "ProductFieldProposal",
    "ProductImage",
    "ProductStatus",
    "StockStatus",
    "SupplierOffer",
    "TechDocument",
]
