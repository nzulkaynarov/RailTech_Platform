"""crm.services — business logic, split into cohesive submodules.

Public API is re-exported here so `crm.services.X` and
`from crm.services import X` keep working unchanged.
"""

from ._params import PaymentData
from .availability import (
    Tranche,
    auto_split_quote_by_availability,
    resolve_seller_offer,
    split_line_by_availability,
)
from .ai_chat import suggest_chat_reply
from .ai_diff import quote_vs_request_diff, user_can_view_quote_diff
from .billing import generate_act, generate_invoice_from_contract, record_payment, sign_act
from .charges import apply_charge_template_to_quote, set_quote_delivery_basis
from .exporters import export_quote
from .contracts import (
    cancel_contract,
    force_cancel_contract,
    generate_contract_from_quote,
    sign_contract_by_client,
    sign_contract_by_manager,
)
from .deals import (
    ALLOWED_STAGE_TRANSITIONS,
    STAGE_REQUIRES_SIGNED_CONTRACT,
    bulk_close_deals_lost,
    convert_lead_to_deal,
    force_transition_deal_stage,
    get_allowed_transitions,
    mark_leads_processed,
    register_new_deal,
    transition_deal_stage,
)
from .fulfillment import ensure_fulfillment, update_fulfillment_status
from .messaging import archive_messages_sync, send_deal_message, user_can_access_deal_chat
from .quotes import (
    QuoteCalculationService,
    QuoteLifecycleService,
    apply_company_quote_defaults,
    effective_quote_lead_time,
    get_crm_analytics_data,
    reassign_quote_item_product,
)
from .rfq import (
    buyer_add_request_item,
    buyer_add_request_items,
    buyer_can_edit_request,
    buyer_remove_request_item,
    buyer_update_request_item,
    buyer_update_request_meta,
    route_request_to_sellers,
    submit_request,
)

__all__ = [
    "ALLOWED_STAGE_TRANSITIONS",
    "PaymentData",
    "QuoteCalculationService",
    "QuoteLifecycleService",
    "STAGE_REQUIRES_SIGNED_CONTRACT",
    "Tranche",
    "apply_charge_template_to_quote",
    "apply_company_quote_defaults",
    "archive_messages_sync",
    "auto_split_quote_by_availability",
    "buyer_add_request_item",
    "buyer_add_request_items",
    "buyer_can_edit_request",
    "buyer_remove_request_item",
    "buyer_update_request_item",
    "buyer_update_request_meta",
    "bulk_close_deals_lost",
    "cancel_contract",
    "convert_lead_to_deal",
    "effective_quote_lead_time",
    "ensure_fulfillment",
    "export_quote",
    "force_cancel_contract",
    "force_transition_deal_stage",
    "generate_act",
    "generate_contract_from_quote",
    "generate_invoice_from_contract",
    "get_allowed_transitions",
    "get_crm_analytics_data",
    "mark_leads_processed",
    "reassign_quote_item_product",
    "record_payment",
    "register_new_deal",
    "resolve_seller_offer",
    "route_request_to_sellers",
    "split_line_by_availability",
    "send_deal_message",
    "set_quote_delivery_basis",
    "sign_act",
    "sign_contract_by_client",
    "sign_contract_by_manager",
    "submit_request",
    "suggest_chat_reply",
    "quote_vs_request_diff",
    "user_can_view_quote_diff",
    "transition_deal_stage",
    "update_fulfillment_status",
    "user_can_access_deal_chat",
]
