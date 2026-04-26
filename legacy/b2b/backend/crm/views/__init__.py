"""
CRM views package.

Re-exports all ViewSets and Views for backwards compatibility so that
``from crm.views import DealViewSet`` continues to work unchanged.
"""

from crm.views.analytics import CRMAnalyticsView, DashboardAnalyticsView  # noqa: F401
from crm.views.bids import SupplierBidViewSet  # noqa: F401
from crm.views.billing import (  # noqa: F401
    ActViewSet,
    ContractViewSet,
    FulfillmentViewSet,
    InvoiceViewSet,
    PaymentViewSet,
    Phase2StatusChoicesView,
)
from crm.views.deals import DealStageViewSet, DealViewSet  # noqa: F401
from crm.views.leads import LeadCreateView, LeadViewSet  # noqa: F401
from crm.views.messages import ActivityLogViewSet, MessageViewSet  # noqa: F401
from crm.views.quotes import QuoteItemViewSet, QuoteStatusViewSet, QuoteViewSet  # noqa: F401

__all__ = [
    # deals
    "DealViewSet",
    "DealStageViewSet",
    # quotes
    "QuoteViewSet",
    "QuoteItemViewSet",
    "QuoteStatusViewSet",
    # messages
    "MessageViewSet",
    "ActivityLogViewSet",
    # analytics
    "DashboardAnalyticsView",
    "CRMAnalyticsView",
    # billing (contracts, invoices, payments, acts, fulfillment)
    "ContractViewSet",
    "InvoiceViewSet",
    "PaymentViewSet",
    "ActViewSet",
    "FulfillmentViewSet",
    "Phase2StatusChoicesView",
    # bids
    "SupplierBidViewSet",
    # leads
    "LeadCreateView",
    "LeadViewSet",
]
