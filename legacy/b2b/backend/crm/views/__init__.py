"""
CRM views package.

Re-exports all ViewSets and Views for backwards compatibility so that
``from crm.views import DealViewSet`` continues to work unchanged.
"""

from crm.views.ai import SuggestChatReplyView  # noqa: F401
from crm.views.ai_diff import QuoteRequestDiffView  # noqa: F401
from crm.views.analytics import DashboardAnalyticsView, TimeToFirstQuoteView  # noqa: F401
from crm.views.billing import (  # noqa: F401
    ActViewSet,
    ContractViewSet,
    FulfillmentViewSet,
    InvoiceViewSet,
    PaymentViewSet,
)
from crm.views.deals import DealStageViewSet, DealViewSet  # noqa: F401
from crm.views.leads import LeadCreateView, LeadViewSet  # noqa: F401
from crm.views.messages import ActivityLogViewSet, MessageViewSet  # noqa: F401
from crm.views.quotes import (  # noqa: F401
    ChargeTemplateViewSet,
    ChargeTypeViewSet,
    PublicQuoteAcceptView,
    PublicQuotePageScriptView,
    PublicQuoteRejectView,
    PublicQuoteRequestCodeView,
    PublicQuoteView,
    PublicQuoteViewedView,
    QuoteChargeViewSet,
    QuoteItemViewSet,
    QuoteStatusViewSet,
    QuoteViewSet,
)
from crm.views.relationships import RelationshipViewSet  # noqa: F401
from crm.views.timeline import TimelineView  # noqa: F401

__all__ = [
    # deals
    "DealViewSet",
    "DealStageViewSet",
    # quotes
    "QuoteViewSet",
    "QuoteItemViewSet",
    "QuoteChargeViewSet",
    "ChargeTypeViewSet",
    "ChargeTemplateViewSet",
    "QuoteStatusViewSet",
    "PublicQuoteView",
    "PublicQuotePageScriptView",
    "PublicQuoteViewedView",
    "PublicQuoteRequestCodeView",
    "PublicQuoteAcceptView",
    "PublicQuoteRejectView",
    # messages
    "MessageViewSet",
    "ActivityLogViewSet",
    # analytics
    "DashboardAnalyticsView",
    "TimeToFirstQuoteView",
    # billing (contracts, invoices, payments, acts, fulfillment)
    "ContractViewSet",
    "InvoiceViewSet",
    "PaymentViewSet",
    "ActViewSet",
    "FulfillmentViewSet",
    # leads
    "LeadCreateView",
    "LeadViewSet",
    # ai
    "SuggestChatReplyView",
    "QuoteRequestDiffView",
    # timeline (CRM Phase A)
    "TimelineView",
    # counterparty book (CRM Phase B)
    "RelationshipViewSet",
]
