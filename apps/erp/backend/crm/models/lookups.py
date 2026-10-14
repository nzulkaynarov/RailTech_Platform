"""CRM lookups — re-exported from sales, finance, and documents per ADR-0006."""

from documents.models.lookups import DocumentTemplateKind, GeneratedDocumentStatus
from finance.models.lookups import ActStatus, InvoiceStatus
from sales.models.lookups import ChargeType, ContractStatus, DealStage, FulfillmentStatus, QuoteStatus

__all__ = [
    "ActStatus",
    "ChargeType",
    "ContractStatus",
    "DealStage",
    "DocumentTemplateKind",
    "FulfillmentStatus",
    "GeneratedDocumentStatus",
    "InvoiceStatus",
    "QuoteStatus",
]
