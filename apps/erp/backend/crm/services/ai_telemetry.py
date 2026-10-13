"""AI match-outcome telemetry (Rule 8 service; spec-remaining-2026-07-07, AI-калибровка).

Three hooks around the AI fuzzy auto-bind in draft-КП generation:

- `record_draft_match_outcomes` — called by `generate_draft_quote` right after the draft lines are
  created: persists the AI top-candidate (bound or below-threshold) per line.
- `resolve_outcome_on_reassign` — called by `reassign_quote_item_product`: the seller's explicit
  verdict on a line (picked another product / cleared / manually bound an AI suggestion).
- `finalize_outcomes_on_send` — called by `send_to_client`: the КП going out to the client is the
  ultimate ground truth, so every row snapshots what the line actually carried; still-PENDING rows
  resolve to SENT.

All three are best-effort bookkeeping on hot commercial paths: they run inside the callers'
transactions and only touch AIMatchOutcome rows, so they cannot corrupt КП data — but they must
never *block* a КП either, hence no additional gates or raises here.
"""

import logging
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from ..models import AIMatchOutcome, Quote, QuoteItem

logger = logging.getLogger(__name__)


def record_draft_match_outcomes(
    quote: Quote,
    telemetry: list,
    item_by_src_pk: dict,
) -> int:
    """Persist one AIMatchOutcome per AI top-candidate proposed during draft generation.

    `telemetry` rows come from `_resolve_ai_catalog_matches` and carry
    {src_pk, line_raw, product_id, confidence, threshold, auto_bound}. `item_by_src_pk` maps the
    buyer request line pk → the created draft QuoteItem. Returns the number of rows written.
    """
    outcomes = [
        AIMatchOutcome(
            quote=quote,
            quote_item=item_by_src_pk.get(entry["src_pk"]),
            seller_company_id=quote.seller_company_id,
            line_raw=(entry.get("line_raw") or "")[:500],
            candidate_product_id=entry["product_id"],
            confidence=Decimal(str(entry["confidence"])).quantize(Decimal("0.001")),
            threshold_used=Decimal(str(entry["threshold"])).quantize(Decimal("0.001")),
            auto_bound=entry["auto_bound"],
            final_product_id=entry["product_id"] if entry["auto_bound"] else None,
        )
        for entry in telemetry
    ]
    AIMatchOutcome.objects.bulk_create(outcomes)
    return len(outcomes)


def resolve_outcome_on_reassign(item: QuoteItem, new_product_id: Optional[int]) -> None:
    """Record the seller's explicit re-match verdict on a draft line.

    Reassign is only possible pre-freeze (QUOTE_FROZEN_CANNOT_REASSIGN guard in the caller), so
    repeated reassigns keep updating the row; `finalize_outcomes_on_send` takes the last snapshot.
    """
    now = timezone.now()
    for outcome in AIMatchOutcome.objects.filter(quote_item=item):
        if new_product_id is None:
            outcome.resolution = AIMatchOutcome.RESOLUTION_CLEARED
        elif outcome.auto_bound:
            outcome.resolution = AIMatchOutcome.RESOLUTION_REASSIGNED
        else:
            outcome.resolution = AIMatchOutcome.RESOLUTION_MANUAL_BOUND
        outcome.final_product_id = new_product_id
        outcome.resolved_at = now
        outcome.save(update_fields=["resolution", "final_product", "resolved_at"])


def finalize_outcomes_on_send(quote: Quote) -> None:
    """Snapshot the sent КП as ground truth for every telemetry row of this quote.

    The sent document is what the seller actually stands behind, so `final_product` is
    re-snapshotted for ALL rows (a line edited via the generic PATCH path would otherwise be
    missed). Rows without a verdict resolve to SENT; a deleted line resolves to CLEARED.
    """
    now = timezone.now()
    for outcome in quote.ai_match_outcomes.select_related("quote_item").all():
        if outcome.quote_item is None:
            # The seller deleted the line from the draft — the candidate was not kept.
            outcome.final_product_id = None
            if outcome.resolution == AIMatchOutcome.RESOLUTION_PENDING:
                outcome.resolution = AIMatchOutcome.RESOLUTION_CLEARED
        else:
            outcome.final_product_id = outcome.quote_item.product_id
            if outcome.resolution == AIMatchOutcome.RESOLUTION_PENDING:
                outcome.resolution = AIMatchOutcome.RESOLUTION_SENT
        if outcome.resolved_at is None:
            outcome.resolved_at = now
        outcome.save(update_fields=["resolution", "final_product", "resolved_at"])
