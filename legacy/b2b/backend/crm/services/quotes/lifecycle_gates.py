"""КП lifecycle GATES — the pure render / send / submit precondition checks.

Split out of ``lifecycle.py`` (DT3 file-length split) — behaviour unchanged, code moved
not rewritten. These are leaf validators: they read a Quote (+ the acting user and/or
pre-computed economics) and either raise ``ValueError(<CODE>)`` (render/send path — the
caller maps the code to HTTP) or return an ``(value, error_code)`` / error-code result
(submit path — the caller maps the tuple). They perform NO writes and NO side effects, so
the KYC-floor / entitlement / loss-prevention / below-floor policy lives in ONE place and
both the admin and DRF surfaces reach it through ``QuoteLifecycleService`` unchanged
(Rule 8 — business logic stays in services).

Economics: the send / submit callers compute it via the patchable
``lifecycle.compute_quote_economics`` global and pass the dict IN; only the render guard
resolves economics here (no test patches the render path).
"""

import logging
from typing import Optional, Tuple

from accounts.services.permissions import routed_seller_company_id
from crm.constants import QuoteStatusCode

from ._shared import _quote_owner_company_id, _quote_seller_company, resolve_quote_recipient
from .pricing import compute_quote_economics

logger = logging.getLogger(__name__)

# S7a (DealHub margin-floor guardrail): the free-text justification required when a КП is
# sent BELOW the company margin floor. Capped so it can't be abused as a free-text dump.
BELOW_FLOOR_JUSTIFICATION_MAX_LEN = 500


def _zero_value_code(quote) -> str:
    """Q3 (honest errors): a КП with a zero/negative total fails for TWO different reasons —
    tell them apart so the seller gets a true message, not «непросчитанные позиции» on an
    empty КП. NO billable ITEM rows at all → the КП is empty (`QUOTE_EMPTY`); rows exist but
    price out to nothing → `QUOTE_HAS_UNPRICED_LINES`."""
    if not quote.items.billable().exists():
        return "QUOTE_EMPTY"
    return "QUOTE_HAS_UNPRICED_LINES"


def assert_renderable(quote):
    """КП render guards; returns the issuing seller company.

    - An unclaimed buyer-request КП (prepared_by NULL) has NO issuing seller, so
      rendering it would brand a "коммерческое предложение" with the platform
      identity ("RailTech B2B") — misrepresenting the supplier on a commercial
      document (audit F1) → QUOTE_NOT_CLAIMED.
    - HOLE 2 (loss-prevention): the render/export surface was the gate bypass — a
      seller could generate a КП PDF on a DRAFT at the placeholder rate 1 (or below
      cost) and hand it to the client out-of-band, never touching submit/send.
      Refuse a client document whose numbers are wrong (no FX rate) or loss-making —
      the same gate as send_to_client.
    """
    seller_company = _quote_seller_company(quote)
    if seller_company is None:
        raise ValueError("QUOTE_NOT_CLAIMED")
    economics = compute_quote_economics(quote)
    if economics["fx_missing"]:
        raise ValueError("FX_RATE_MISSING")
    if economics["below_cost"]:
        raise ValueError("QUOTE_BELOW_COST")
    return seller_company


def assert_sendable(quote, sent_by_user):
    """Non-economics send preconditions; returns the issuing seller company.

    Runs the status / recipient / claim / KYC-floor / entitlement gates in the exact
    order ``send_to_client`` used to inline them (order is contractual — an unverified
    seller must see "do KYC" before a generic billing error).
    """
    # Status guard: only an internally-approved КП (READY_TO_SEND — it passed
    # the sales → ВЭД → director chain) may go out to the client.
    current = quote.status.code if quote.status else "None"
    if current != QuoteStatusCode.READY_TO_SEND:
        raise ValueError(
            f"Cannot send quote in status '{current}'. "
            "Only READY_TO_SEND quotes (internally approved) can be sent to the client."
        )

    # RECIPIENT GATE (B5): a КП with nobody to send it to must not be marked SENT. The async
    # email task used to log a warning and return `no_recipient` while the КП was already
    # frozen + SENT and the deal moved to QUOTE_SENT — «отправлено в никуда», invisible to the
    # seller. Synchronous and BEFORE any state change, using the SAME resolver the task uses,
    # so the two can never disagree about what "has a recipient" means.
    if resolve_quote_recipient(quote) is None:
        raise ValueError("RECIPIENT_REQUIRED")

    # An unclaimed КП has no issuing seller (e.g. the preparer's membership was deactivated
    # after the КП was claimed) — refuse to send rather than freeze it under the PLATFORM
    # identity, mint a platform-branded number, and then have the async PDF render fail
    # (audit M2). Mirrors the generate_pdf QUOTE_NOT_CLAIMED guard so the failure surfaces
    # synchronously to the sender. A superuser send is the platform-escalation/orchestrator
    # path (no company membership by design) and is allowed through with platform branding.
    seller_company = _quote_seller_company(quote)
    if seller_company is None and not getattr(sent_by_user, "is_superuser", False):
        raise ValueError("QUOTE_NOT_CLAIMED")

    # Wave E F3 / B5 — RECIPIENT GATE. A company-less «калькулятор» draft (Deal.company
    # NULL, no contact, no registered client) has NOBODY to send to: the email task would
    # log "no recipient" and skip, yet the КП would be frozen, numbered and marked SENT —
    # "sent into the void". Refuse SYNCHRONOUSLY so the seller is prompted to pick or
    # create a recipient first. NOTE: a parallel lane (fix/wave-a-money-path) introduces
    # `resolve_quote_recipient` in `_shared.py` raising this SAME code from this same
    # guard slot; on merge, keep that richer resolver and drop this block — the contract
    # ({"detail": "RECIPIENT_REQUIRED"}) is identical either way.
    deal_for_send = quote.deal
    if not (deal_for_send.company_id or deal_for_send.contact_id or deal_for_send.client_id):
        raise ValueError("RECIPIENT_REQUIRED")

    # SELLER FLOOR (ADR-0006 Phase E): «без KYC только демо». A seller must be KYC-verified (L2+)
    # to send a real КП — checked first so an unverified seller gets a clear "do KYC" message
    # rather than a generic billing error. Then the MONETIZATION GATE (Move 4): sending is a PAID
    # action needing the quote.send entitlement (an operational subscription grants it). A
    # demo/unsubscribed seller can build the КП but not send it. Superuser = platform escalation.
    if seller_company is not None and not getattr(sent_by_user, "is_superuser", False):
        from accounts.services import quote_send_entitled
        from accounts.services.kyc import company_kyc_verified

        if not company_kyc_verified(seller_company.id):
            raise ValueError("SELLER_KYC_REQUIRED")
        if not quote_send_entitled(seller_company.id):
            raise ValueError("QUOTE_SEND_NOT_ENTITLED")

    return seller_company


def assert_send_economics(quote, economics, justification) -> None:
    """Economics + below-floor guardrail for a send (economics computed by the caller).

    LOSS PREVENTION (authoritative server gate): never send a КП priced below its landed
    cost — even if items/charges were edited after the internal approval. Mirrors the
    live G1 guardrail in the builder; can't be bypassed via the API.
    A value-less КП (no priced lines) must not go to the client even if it carries charges
    (HOLE 4 — submit had this guard, send did not; items can change after READY_TO_SEND).

    BELOW-FLOOR GUARDRAIL (S7a, DealHub standard): sending a КП under the company margin
    FLOOR is allowed (self-approve — NOT approval-routing, unlike the hard below_cost block)
    but must carry a written justification that lands in the audit trail. Length-capped so it
    can't be abused. Above-floor sends require nothing and log no special event. The gate is
    server-authoritative: it fires even for a sender WITHOUT cost visibility (who never saw
    below_floor on the client), so the SPA re-prompts on the error code. ``justification`` is
    expected pre-stripped by the caller.
    """
    if (quote.subtotal_excl_vat or 0) <= 0:
        raise ValueError(_zero_value_code(quote))
    if economics["fx_missing"]:
        raise ValueError("FX_RATE_MISSING")
    if economics["below_cost"]:
        raise ValueError("QUOTE_BELOW_COST")
    if len(justification) > BELOW_FLOOR_JUSTIFICATION_MAX_LEN:
        raise ValueError("JUSTIFICATION_TOO_LONG")
    if economics["below_floor"] and not justification:
        raise ValueError("BELOW_FLOOR_JUSTIFICATION_REQUIRED")


def resolve_submit_company(quote, actor) -> Tuple[Optional[int], Optional[str]]:
    """Resolve the КП-owning company for a submit WITHOUT mutating anything (audit F0).

    Returns ``(company_id, None)`` on success or ``(None, error_code)`` for the caller.

    - already-claimed КП → the preparer's company;
    - unclaimed buyer-request КП → the submitter MAY claim it, but ONLY if they are a
      can_sell seller routed to THIS deal. Anchoring prepared_by before this check let any
      authenticated user (even a buyer) hijack the КП + drive its approval chain
      cross-tenant, and the write committed even on a rejected call.

    ADR-0005 Phase E U3 Step 2: gate the approval-chain ENTRY on the quote.build CompanyRole
    permission instead of the SALES_MANAGER WorkspaceRole — "gate on the capability, not the
    role title". member_has_permission scopes to company_id (no buyer/cross-tenant leak; a
    can_sell=False buyer is denied).
    """
    if quote.prepared_by_id:
        company_id = _quote_owner_company_id(quote)
        if not company_id:
            return None, "NO_QUOTE_COMPANY"
    else:
        company_id = routed_seller_company_id(actor, quote.deal_id)
        if not company_id:
            return None, "ROLE_NOT_PERMITTED"

    from accounts.services.permissions import member_has_permission

    if not member_has_permission(actor, company_id, "quote.build"):
        return None, "ROLE_NOT_PERMITTED"
    return company_id, None


def assert_submittable(quote, economics) -> Optional[str]:
    """Status + value + loss-prevention gate for entering the approval chain.

    Returns an error code (for the caller to map) or ``None`` when the КП may proceed.

    - DRAFT-only status guard.
    - A commercial offer cannot enter the chain with NO value: reject a КП whose TOTAL is
      zero/negative (keyed on the КП total, not per-line, so a deliberately-free line among
      priced lines is still allowed — audit M6).
    - LOSS PREVENTION (hard stop): a КП whose client total is below its landed cost would be
      sold at a loss — never allow it in. Below the margin FLOOR is a softer signal (warn +
      approval on the client side), NOT a hard block here.
    """
    if not quote.status or quote.status.code != QuoteStatusCode.DRAFT:
        return "INVALID_STATUS"
    if (quote.subtotal_excl_vat or 0) <= 0:
        return _zero_value_code(quote)
    if economics["fx_missing"]:
        return "FX_RATE_MISSING"
    if economics["below_cost"]:
        return "QUOTE_BELOW_COST"
    return None
