"""Shared КП acceptance / rejection cores — ONE source for both the logged-in buyer path and
the offline email-code (contact) path (Rule 8: no duplicated FSM between surfaces).

`QuoteLifecycleService.approve_quote` / `reject_quote` (registered buyer) and the Wave-A public
page's contact endpoints both delegate here. The only difference between the two callers is the
acceptor IDENTITY: a registered buyer has a `CustomUser` (`approved_by_user`); an offline contact
has none, so `approved_by` stays NULL and the contact's email + request IP are recorded in the
timeline event_params instead. Everything else — the SENT status guard, the FSM transition,
contract materialization, seller notification — is identical and lives here once.

Legal honesty: a contact acceptance is a commercial acceptance (коммерческий акцепт) with an
audit trail, NOT a qualified e-signature (E-IMZO is not implemented). The contract is still
signed later via the existing MANUAL_MODE flow.
"""

import logging

from django.db import transaction
from django.utils import timezone

from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import Quote, QuoteStatus
from crm.services.deals import transition_deal_stage

from ._shared import _log_quote, _notify_quote_outcome, _quote_client_display_name

logger = logging.getLogger(__name__)


@transaction.atomic
def perform_quote_acceptance(quote_id, *, approved_by_user=None, contact_email=None, request_ip=None) -> Quote:
    """Accept a SENT КП → APPROVED, advance the FSM, materialize the contract, notify the seller.

    `approved_by_user` set = registered-buyer path (recorded as `approved_by`). `approved_by_user`
    None = offline-contact path: `approved_by` stays NULL and the contact email + IP are captured
    in the timeline audit. Atomic: any failure (bad status / FSM guard) rolls the whole accept back.
    """
    quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

    current = quote.status.code if quote.status else "None"
    if current != QuoteStatusCode.SENT:
        raise ValueError(f"Cannot approve quote in status '{current}'. Only SENT quotes can be approved.")

    approved_status = QuoteStatus.objects.filter(code=QuoteStatusCode.APPROVED).first()
    quote.status = approved_status
    quote.approved_at = timezone.now()
    quote.approved_by = approved_by_user
    quote.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])

    # Change deal stage via FSM (P0-1: capture the error — don't swallow it).
    _, stage_err = transition_deal_stage(
        quote.deal,
        DealStageCode.CONTRACT_SIGNED,
        actor=approved_by_user,
        reason=f"КП v{quote.version} одобрено клиентом",
    )
    if stage_err:
        raise ValueError(stage_err)

    # Materialize the Contract the instant the buyer accepts (audit B1). actor=None = system path:
    # the acceptance triggers it and the acceptor (buyer OR offline contact) is not a seller, so it
    # must NOT go through the seller-actor guard. Best-effort — a render hiccup must not unwind the
    # acceptance (the seller can re-issue from the contract surface).
    from crm.services.contracts import generate_contract_from_quote

    try:
        generate_contract_from_quote(quote.id, actor=None)
    except (ValueError, OSError) as exc:  # noqa: BLE001 — narrow: lookup/PDF render
        logger.warning("Contract auto-generation after acceptance failed for quote %s: %s", quote.id, exc)

    # Notify the КП author (+ distinct manager) that the client accepted. Pushed over WS.
    _notify_quote_outcome(
        quote,
        type_code="SUCCESS",
        title="КП одобрено клиентом",
        message=f"{_quote_client_display_name(quote)} одобрил КП v{quote.version}",
        event_code="quote.accepted_by_client",
        event_params={"client": _quote_client_display_name(quote), "version": quote.version},
    )

    # Counterparty timeline (Phase A): the acceptance itself as a first-class event.
    event_params = {"version": quote.version, "number": quote.number or "—"}
    detail = f"КП v{quote.version} ({quote.number or '—'})"
    if approved_by_user is None:
        # Offline-contact acceptance — record channel + who (email) + IP for the audit trail.
        event_params.update(
            {"channel": "offline_contact", "contact_email": contact_email or "", "ip": request_ip or ""}
        )
        detail = f"КП v{quote.version} ({quote.number or '—'}) — офлайн-акцепт по email-коду"
    _log_quote(
        quote,
        approved_by_user,
        "КП принято клиентом",
        detail,
        event_code="quote.accepted",
        event_params=event_params,
    )
    return quote


@transaction.atomic
def perform_quote_rejection(
    quote_id, *, rejected_by_user=None, reason="", contact_email=None, request_ip=None
) -> Quote:
    """Reject a SENT КП → REJECTED, move the deal back to CALCULATING, notify the seller.

    Mirrors :func:`perform_quote_acceptance`: `rejected_by_user` None = offline-contact path
    (`channel=offline_contact`, email + IP in event_params). The reason is kept off `quote.notes`
    (that field renders in the client КП PDF) — it lives on the stage-transition audit + timeline.
    """
    reason = (reason or "").strip()
    quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

    current = quote.status.code if quote.status else "None"
    if current != QuoteStatusCode.SENT:
        raise ValueError(f"Cannot reject quote in status '{current}'. Only SENT quotes can be rejected.")

    rejected_status = QuoteStatus.objects.filter(code=QuoteStatusCode.REJECTED).first()
    quote.status = rejected_status
    quote.save(update_fields=["status", "updated_at"])

    _, stage_err = transition_deal_stage(
        quote.deal,
        DealStageCode.CALCULATING,
        actor=rejected_by_user,
        reason=f"КП v{quote.version} отклонено. {reason}",
    )
    if stage_err:
        raise ValueError(stage_err)

    _notify_quote_outcome(
        quote,
        type_code="WARNING",
        title="КП отклонено клиентом",
        message=f"{_quote_client_display_name(quote)} отклонил КП v{quote.version}. {reason}".strip(),
        event_code="quote.rejected_by_client",
        event_params={"client": _quote_client_display_name(quote), "version": quote.version, "reason": reason},
    )

    # `reason` кладём ВСЕГДА (не только для офлайн-контакта): лента показывает вариант
    # `detail_reason`, когда причина есть, — до 17-08 продавец видел «КП отклонено клиентом,
    # КП v2» и нигде на экране не находил, ПОЧЕМУ (найдено прогоном глазами).
    event_params = {"version": quote.version, "reason": reason}
    detail = f"КП v{quote.version}" + (f" — {reason}" if reason else "")
    if rejected_by_user is None:
        event_params.update(
            {
                "channel": "offline_contact",
                "contact_email": contact_email or "",
                "ip": request_ip or "",
            }
        )
        detail = f"КП v{quote.version} — отклонено офлайн-контактом. {reason}".strip()
    _log_quote(
        quote,
        rejected_by_user,
        "КП отклонено клиентом",
        detail,
        event_code="quote.rejected",
        event_params=event_params,
    )
    return quote
