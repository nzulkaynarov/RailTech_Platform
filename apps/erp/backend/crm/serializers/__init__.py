"""crm.serializers — DRF serializers, split into cohesive submodules.

Historically one ~1030-line ``crm/serializers.py`` module; split (ARCH refactor,
mechanical, behaviour-preserving) into:

  * ``item``    — QuoteItemSerializer (line-item, seller-cost redaction)
  * ``charge``  — ChargeType / ChargeTemplate / QuoteCharge serializers
  * ``quote``   — QuoteApprovalStep + Quote document serializer
  * ``deal``    — Deal list/detail + viewer-side helpers
  * ``misc``    — ActivityLog
  * ``billing`` — Contract / Invoice / InvoiceItem / Payment / Act / Fulfillment

The ENTIRE public surface is re-exported here so every existing
``from crm.serializers import X`` keeps working unchanged.
"""

from .billing import (
    ActSerializer,
    ContractSerializer,
    FulfillmentSerializer,
    InvoiceItemSerializer,
    InvoiceSerializer,
    PaymentSerializer,
)
from .charge import ChargeTemplateSerializer, ChargeTypeSerializer, QuoteChargeSerializer
from .deal import DealDetailSerializer, DealListSerializer
from .documents import DocumentTemplateSerializer, GeneratedDocumentSerializer
from .item import QuoteItemSerializer
from .misc import ActivityLogSerializer
from .numbering import (
    NumberingPreviewRequestSerializer,
    NumberingPreviewResponseSerializer,
    NumberingSchemeSerializer,
    NumberingSchemeWriteSerializer,
)
from .quote import QuoteApprovalStepSerializer, QuoteSerializer

__all__ = [
    # quote family
    "QuoteApprovalStepSerializer",
    "QuoteItemSerializer",
    "ChargeTypeSerializer",
    "ChargeTemplateSerializer",
    "QuoteChargeSerializer",
    "QuoteSerializer",
    # deals
    "DealListSerializer",
    "DealDetailSerializer",
    # documents ("Документы 2.0")
    "DocumentTemplateSerializer",
    "GeneratedDocumentSerializer",
    # numbering (N2 editor)
    "NumberingSchemeSerializer",
    "NumberingSchemeWriteSerializer",
    "NumberingPreviewRequestSerializer",
    "NumberingPreviewResponseSerializer",
    # misc
    "ActivityLogSerializer",
    # billing
    "ContractSerializer",
    "InvoiceItemSerializer",
    "PaymentSerializer",
    "InvoiceSerializer",
    "ActSerializer",
    "FulfillmentSerializer",
]
