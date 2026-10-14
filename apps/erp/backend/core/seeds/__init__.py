"""Central registry and exports for ERP seed data."""

from .accounts import ROLE_APPLICABILITY, SYSTEM_ROLES, WORKSPACE_ROLES, seed_roles, widen_ved_applicability
from .beat import seed_beat_tasks
from .catalog import CATEGORIES, DOMAIN_TYPES, PRODUCT_STATUSES, STOCK_STATUSES, seed_catalog_lookups
from .countries import CURATED_VAT, ISO_COUNTRIES, ISO_COUNTRY_COUNT, seed_countries
from .currencies import CURRENCIES, seed_currencies
from .delivery_basis import INCOTERMS, seed_incoterms
from .documents import (
    DOCUMENT_STATUSES,
    SAMPLE_TEMPLATES,
    TEMPLATE_KINDS,
    extract_placeholders,
    seed_document_lookups_and_samples,
)
from .finance import ACT_STATUSES, INVOICE_STATUSES, seed_finance_lookups
from .notifications import NOTIFICATION_TYPES, seed_notification_types
from .parties import COMPANY_TYPES, seed_company_types
from .sales import (
    CHARGE_TEMPLATES,
    CHARGE_TYPES,
    CONTRACT_STATUSES,
    DEAL_STAGES,
    FREIGHT_BASES,
    FULFILLMENT_STATUSES,
    QUOTE_STATUSES,
    seed_basis_freight,
    seed_charge_engine,
    seed_sales_lookups,
)
from .settings import seed_system_settings
from .uom import UOM_CODES, seed_uom

__all__ = [
    "ACT_STATUSES",
    "CATEGORIES",
    "CHARGE_TEMPLATES",
    "CHARGE_TYPES",
    "COMPANY_TYPES",
    "CONTRACT_STATUSES",
    "CURATED_VAT",
    "CURRENCIES",
    "DEAL_STAGES",
    "DOCUMENT_STATUSES",
    "DOMAIN_TYPES",
    "FREIGHT_BASES",
    "FULFILLMENT_STATUSES",
    "INCOTERMS",
    "INVOICE_STATUSES",
    "ISO_COUNTRIES",
    "ISO_COUNTRY_COUNT",
    "NOTIFICATION_TYPES",
    "PRODUCT_STATUSES",
    "QUOTE_STATUSES",
    "ROLE_APPLICABILITY",
    "SAMPLE_TEMPLATES",
    "STOCK_STATUSES",
    "SYSTEM_ROLES",
    "TEMPLATE_KINDS",
    "UOM_CODES",
    "WORKSPACE_ROLES",
    "extract_placeholders",
    "seed_basis_freight",
    "seed_beat_tasks",
    "seed_catalog_lookups",
    "seed_charge_engine",
    "seed_company_types",
    "seed_countries",
    "seed_currencies",
    "seed_document_lookups_and_samples",
    "seed_finance_lookups",
    "seed_incoterms",
    "seed_notification_types",
    "seed_roles",
    "seed_sales_lookups",
    "seed_system_settings",
    "seed_uom",
    "widen_ved_applicability",
]
