"""
CRM views package.

Re-exports all ViewSets and Views for backwards compatibility so that
``from crm.views import DealViewSet`` continues to work unchanged.
"""

from crm.views.activity_logs import ActivityLogViewSet  # noqa: F401
from crm.views.ai_diff import QuoteRequestDiffView  # noqa: F401
from crm.views.analytics import (  # noqa: F401
    DashboardAnalyticsView,
    RecentDocumentsView,
    SearchDocumentsView,
    TimeToFirstQuoteView,
)
from crm.views.billing import (  # noqa: F401
    ActViewSet,
    ContractViewSet,
    FulfillmentViewSet,
    InvoiceViewSet,
    PaymentViewSet,
)
from crm.views.deals import DealStageViewSet, DealViewSet  # noqa: F401
from crm.views.documents import DocumentTemplateViewSet, GeneratedDocumentViewSet  # noqa: F401
from crm.views.documents_public import PublicDocumentView  # noqa: F401
from crm.views.numbering import NumberingSchemePreviewView, NumberingSchemeView  # noqa: F401
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
from crm.views.wording import WordingVariantViewSet  # noqa: F401

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
    # activity log
    "ActivityLogViewSet",
    # numbering (N2 editor)
    "NumberingSchemeView",
    "NumberingSchemePreviewView",
    # analytics
    "DashboardAnalyticsView",
    "RecentDocumentsView",
    "SearchDocumentsView",
    "TimeToFirstQuoteView",
    # billing (contracts, invoices, payments, acts, fulfillment)
    "ContractViewSet",
    "InvoiceViewSet",
    "PaymentViewSet",
    "ActViewSet",
    "FulfillmentViewSet",
    # ai
    "QuoteRequestDiffView",
    # timeline (CRM Phase A)
    "TimelineView",
    # counterparty book (CRM Phase B)
    "RelationshipViewSet",
    # documents ("Документы 2.0")
    "DocumentTemplateViewSet",
    "WordingVariantViewSet",
    "GeneratedDocumentViewSet",
    "PublicDocumentView",
]
