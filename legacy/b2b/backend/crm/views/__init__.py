"""
CRM views package.

Re-exports all ViewSets and Views for backwards compatibility so that
``from crm.views import DealViewSet`` continues to work unchanged.
"""

from crm.views.deals import DealViewSet, DealStageViewSet  # noqa: F401
from crm.views.quotes import QuoteViewSet, QuoteItemViewSet, QuoteStatusViewSet  # noqa: F401
from crm.views.messages import MessageViewSet, ActivityLogViewSet  # noqa: F401
from crm.views.analytics import DashboardAnalyticsView, CRMAnalyticsView  # noqa: F401
from crm.views.billing import (  # noqa: F401
    ContractViewSet, InvoiceViewSet, PaymentViewSet,
    ActViewSet, FulfillmentViewSet, Phase2StatusChoicesView,
)
from crm.views.bids import SupplierBidViewSet  # noqa: F401
from crm.views.leads import LeadCreateView, LeadViewSet  # noqa: F401

__all__ = [
    # deals
    'DealViewSet',
    'DealStageViewSet',
    # quotes
    'QuoteViewSet',
    'QuoteItemViewSet',
    'QuoteStatusViewSet',
    # messages
    'MessageViewSet',
    'ActivityLogViewSet',
    # analytics
    'DashboardAnalyticsView',
    'CRMAnalyticsView',
    # billing (contracts, invoices, payments, acts, fulfillment)
    'ContractViewSet',
    'InvoiceViewSet',
    'PaymentViewSet',
    'ActViewSet',
    'FulfillmentViewSet',
    'Phase2StatusChoicesView',
    # bids
    'SupplierBidViewSet',
    # leads
    'LeadCreateView',
    'LeadViewSet',
]
