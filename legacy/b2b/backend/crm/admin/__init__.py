"""admin package — split from a monolithic module.

Public API re-exported so existing import paths keep working.
"""

from .billing_admin import ActAdmin, ContractAdmin, FulfillmentAdmin, InvoiceAdmin, PaymentAdmin, SupplierBidAdmin
from .deals_admin import ActivityLogAdmin, CRMLookupAdmin, DealAdmin, LeadAdmin, MessageAdmin
from .inlines import InvoiceItemInline, PaymentInline, QuoteInline, QuoteItemInline, SupplierBidItemInline
from .quotes_admin import QuoteAdmin, QuoteItemHistoryAdmin

__all__ = [
    "ActAdmin",
    "ActivityLogAdmin",
    "CRMLookupAdmin",
    "ContractAdmin",
    "DealAdmin",
    "FulfillmentAdmin",
    "InvoiceAdmin",
    "InvoiceItemInline",
    "LeadAdmin",
    "MessageAdmin",
    "PaymentAdmin",
    "PaymentInline",
    "QuoteAdmin",
    "QuoteInline",
    "QuoteItemHistoryAdmin",
    "QuoteItemInline",
    "SupplierBidAdmin",
    "SupplierBidItemInline",
]
