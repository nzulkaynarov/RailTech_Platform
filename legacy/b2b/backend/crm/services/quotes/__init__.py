"""crm.services.quotes — the КП (commercial-offer) service, split into cohesive submodules.

Historically one ~1500-line ``crm/services/quotes.py`` module; split (ARCH refactor,
mechanical, behaviour-preserving) into:

  * ``_shared``   — leaf helpers (company resolution, doc-profile branding, status
                    mutation, notifications, activity log)
  * ``pricing``   — financial engine (per-line prices, FX, recalculation, economics)
  * ``access``    — viewer scoping, company defaults, send-permission gate,
                    approval queue, public-link reachability gate
  * ``lifecycle`` — QuoteLifecycleService (render/send/approve/reject/submit/force)
  * ``bulk``      — all-or-nothing bulk create/update of КП line items + product re-match

The ENTIRE public (and previously-imported private) surface is re-exported here so that
every existing ``from crm.services.quotes import X`` keeps working unchanged.
"""

from ._shared import (
    _log_quote,
    _notify_quote_outcome,
    _profile_has_branding,
    _quote_client_display_name,
    _quote_owner_company_id,
    _quote_seller_company,
    _seller_document_profile,
    _set_quote_status,
    resolve_quote_recipient,
)
from .access import (
    _EXPIRED_STATUS_CODE,
    _has_legacy_send_role,
    apply_company_quote_defaults,
    approval_queue_for,
    can_duplicate_quote,
    can_send_quote_to_client,
    public_quote_gate,
    reapply_company_defaults,
    scope_quotes_for_viewer,
)
from .bulk import (
    _BULK_CREATE_WRITABLE_FIELDS,
    _BULK_ITEM_WRITABLE_FIELDS,
    _validate_bulk_create_rows,
    _validate_bulk_item_rows,
    bulk_create_quote_items,
    bulk_delete_quote_items,
    bulk_update_quote_items,
    reassign_quote_item_product,
)
from .duplicate import duplicate_quote
from .lifecycle import QuoteLifecycleService
from .pricing import QuoteCalculationService, _positive_fx_rate, compute_quote_economics, effective_quote_lead_time

__all__ = [
    # _shared
    "_quote_owner_company_id",
    "_quote_seller_company",
    "_quote_client_display_name",
    "_seller_document_profile",
    "_profile_has_branding",
    "_set_quote_status",
    "_notify_quote_outcome",
    "_log_quote",
    "resolve_quote_recipient",
    # pricing
    "QuoteCalculationService",
    "compute_quote_economics",
    "effective_quote_lead_time",
    "_positive_fx_rate",
    # access
    "scope_quotes_for_viewer",
    "apply_company_quote_defaults",
    "reapply_company_defaults",
    "can_duplicate_quote",
    "duplicate_quote",
    "can_send_quote_to_client",
    "_has_legacy_send_role",
    "approval_queue_for",
    "public_quote_gate",
    "_EXPIRED_STATUS_CODE",
    # lifecycle
    "QuoteLifecycleService",
    # bulk
    "bulk_update_quote_items",
    "bulk_create_quote_items",
    "bulk_delete_quote_items",
    "reassign_quote_item_product",
    "_validate_bulk_item_rows",
    "_validate_bulk_create_rows",
    "_BULK_ITEM_WRITABLE_FIELDS",
    "_BULK_CREATE_WRITABLE_FIELDS",
]
