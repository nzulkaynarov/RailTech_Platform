"""Duplicate a КП (Odoo Sales «Duplicate» pattern) — deep-copy a quote into a new DRAFT version.

Product benchmark: Odoo's «Duplicate» on a quotation clones every order line + terms into a fresh
draft the salesperson then tweaks; the post-send «create v2» here used to mint an EMPTY draft, so a
seller re-keyed the whole КП. This service does the deep copy: a NEW ``Quote`` on the SAME deal,
status DRAFT, ``version = max(version)+1``, cloning all line items (ITEM/SECTION/NOTE, optional
flag, position, per-line margin NULL/0 semantics), all document charges, and the КП settings.

Deliberately NOT copied (see ``_EXCLUDED`` rationale in the code): the public link token/state,
view/freeze/approve artefacts, the rendered PDF, the human КП number (all minted later on send),
and — critically — ``fx_snapshot`` / ``fx_manual``: the copy must re-freeze CURRENT rates on its
first recalc, so inheriting a stale snapshot would silently price the new КП at an old rate.
"""

import logging

from django.db import transaction
from django.db.models import Max

from crm.constants import QuoteStatusCode
from crm.models import Quote, QuoteCharge, QuoteItem, QuoteStatus

from ._shared import _log_quote
from .pricing import QuoteCalculationService

logger = logging.getLogger(__name__)

# КП-level settings carried over verbatim (task list + ``notes``, the offer body text a
# «same as last one» duplicate must keep). Everything else on the new Quote is either
# regenerated (version / status / prepared_by), minted on send, a buyer-decision artefact,
# or a re-frozen snapshot — see the create() call below.
_COPIED_QUOTE_FIELDS = (
    "quote_currency_id",
    "cost_currency_default_id",
    "vat_rate",
    "tax_country_id",
    "margin_percent",
    "delivery_basis_id",
    "delivery_lead_time_days",
    "delivery_note",
    "valid_until",
    "notes",
)

# Content fields cloned onto each new QuoteItem. `margin_percent` is copied BY VALUE, so the DT1
# semantics survive intact: NULL («inherit the КП margin») stays NULL, an explicit 0 («sell at
# cost») stays 0. The computed columns (landed_cost / final_price_excl_vat) and the optimistic-lock
# `version` are intentionally omitted — recalculate_quote rebuilds them from scratch.
_COPIED_ITEM_FIELDS = (
    "display_type",
    "is_optional",
    "position",
    "product_id",
    "offer_id",
    "imported_raw_name",
    "name_canonical",
    "quantity",
    "unit",
    "unit_code",
    "mpn",
    "gost_drawing",
    "hs_code",
    "note",
    "assigned_at",
    "frozen_base_price",
    "frozen_currency_id",
    "logistics_cost",
    "customs_duty",
    "margin_percent",
    "discount_percent",
    "lead_time_days",
)

# Content fields cloned onto each new QuoteCharge. resolved_base / resolved_amount are transparency
# snapshots the cascade recompute writes, so they are left to recalculate_quote.
_COPIED_CHARGE_FIELDS = (
    "charge_type_id",
    "description",
    "amount",
    "rate_percent",
    "cost_amount",
    "is_deduction",
    "from_template",
    "sort_order",
)


@transaction.atomic
def duplicate_quote(quote_id: int, actor) -> Quote:
    """Deep-copy КП ``quote_id`` into a NEW DRAFT quote on the same deal (version = max+1).

    Authorization is the caller's job (view / ``can_duplicate_quote``) — this is the pure
    copy-and-recalc core (Rule 8). Returns the freshly-recalculated new Quote.
    """
    source = Quote.objects.select_related("deal").prefetch_related("items", "charges").get(pk=quote_id)

    next_version = (source.deal.quotes.aggregate(mx=Max("version"))["mx"] or 0) + 1
    draft_status = QuoteStatus.objects.get(code=QuoteStatusCode.DRAFT)

    new_quote = Quote.objects.create(
        deal=source.deal,
        version=next_version,
        status=draft_status,
        # The seller who clicks «Duplicate» owns the new draft; ownership company is kept
        # stable (the source's owning seller — same deal, same seller lane).
        prepared_by=actor,
        seller_company_id=source.seller_company_id,
        # fx_snapshot / fx_manual are LEFT at the model default ({}) on purpose — the first
        # recalculate_quote below re-freezes today's rates. Inheriting the source snapshot
        # would silently price the copy at a stale FX rate.
        **{field: getattr(source, field) for field in _COPIED_QUOTE_FIELDS},
    )

    # Clone line items + charges in bulk (bypasses per-row save/recalc); recalculate_quote
    # rebuilds landed_cost/final_price + the header totals in one pass afterwards.
    new_items = [
        QuoteItem(quote=new_quote, **{field: getattr(item, field) for field in _COPIED_ITEM_FIELDS})
        for item in source.items.all()
    ]
    if new_items:
        QuoteItem.objects.bulk_create(new_items)
    new_charges = [
        QuoteCharge(
            quote=new_quote, created_by=actor, **{field: getattr(charge, field) for field in _COPIED_CHARGE_FIELDS}
        )
        for charge in source.charges.all()
    ]
    if new_charges:
        QuoteCharge.objects.bulk_create(new_charges)

    # Recalculate: freezes a FRESH fx_snapshot and computes subtotal/charges/VAT/total so the
    # copy's totals are correct from the start (not inherited from the source).
    QuoteCalculationService.recalculate_quote(new_quote.pk)
    new_quote.refresh_from_db()

    _log_quote(
        new_quote,
        actor,
        "КП дублировано",
        f"КП v{new_quote.version} создано копированием КП v{source.version} ({source.number or '—'})",
        event_code="quote.duplicated",
        event_params={"version": new_quote.version, "source_version": source.version, "source_quote_id": source.id},
    )
    return new_quote
