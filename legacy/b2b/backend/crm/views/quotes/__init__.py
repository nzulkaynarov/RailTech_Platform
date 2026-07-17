"""crm.views.quotes — КП API views, split into cohesive submodules.

Historically one ~1270-line ``crm/views/quotes.py`` module; split (ARCH refactor,
mechanical, behaviour-preserving) into:

  * ``public``  — PublicQuoteView (unauthenticated token view/download)
  * ``quotes``  — QuoteViewSet (CRUD + lifecycle + approval chain + PDF/export)
  * ``items``   — QuoteItemViewSet + the seller-owns-deal write guard
  * ``charges`` — QuoteCharge / QuoteStatus / ChargeType / ChargeTemplate ViewSets

Every ViewSet/View is re-exported here so ``from crm.views.quotes import X``
(the ``crm.views`` package re-export → ``core/urls.py`` router) keeps working unchanged.
"""

from .charges import (
    ChargeTemplateViewSet,
    ChargeTypeViewSet,
    QuoteChargeViewSet,
    QuoteStatusViewSet,
)
from .items import QuoteItemViewSet
from .public import PublicQuoteView
from .quotes import QuoteViewSet

__all__ = [
    "PublicQuoteView",
    "QuoteViewSet",
    "QuoteItemViewSet",
    "QuoteChargeViewSet",
    "QuoteStatusViewSet",
    "ChargeTypeViewSet",
    "ChargeTemplateViewSet",
]
