"""КП visibility, permission gates and public-link reachability.

Read-side / gate helpers split out of the monolithic ``crm/services/quotes.py``
(ARCH refactor) — behaviour unchanged: the hidden-competition queryset scope, the
company-defaults pre-fill, the send-permission gate, the approval-queue query and the
public no-login link gate. Depends only on the leaf ``_shared`` helpers.
"""

from decimal import Decimal
from typing import Optional

from django.db import models

from accounts.constants import WorkspaceRoleCode
from accounts.models import Company
from crm.constants import QuoteStatusCode
from crm.models import Quote
from crm.services._params import has_explicit_company_role_perm

from ._shared import _quote_owner_company_id


def scope_quotes_for_viewer(quotes_qs, user, request):
    """Restrict a Quote queryset to what the viewer may see — the SINGLE source of the
    hidden-competition boundary (audit #2). A seller acting in a seller context sees only
    quotes prepared by their OWN seller companies (or unassigned drafts); a platform admin
    and a buyer in own-deal context see all. Used by BOTH QuoteViewSet.get_queryset AND the
    deal-nested `quotes`/`active_quote` prefetch (DealViewSet), so the two surfaces cannot
    diverge and leak a competitor's КП (prices/totals/margin/PDF) on a multi-seller deal."""
    from accounts.services.permissions import (
        seller_acting_company_ids,
        seller_visible_deal_ids,
    )

    if getattr(user, "is_platform_admin", False):
        return quotes_qs
    if seller_visible_deal_ids(user, request) is not None:
        seller_ids = seller_acting_company_ids(user, request) or set()
        return quotes_qs.filter(
            models.Q(
                prepared_by__memberships__company_id__in=seller_ids,
                prepared_by__memberships__is_active=True,
            )
            | models.Q(prepared_by__isnull=True)
        ).distinct()
    return quotes_qs


def apply_company_quote_defaults(quote: Quote, company: Optional[Company]) -> Quote:
    """Pre-fill a freshly-CREATED КП from the seller company's CompanySettings.

    Only fills fields the company has actually configured (non-None), and ONLY on a
    brand-new quote — never overwrites a value already set on the quote. Applied to:
    delivery_basis, quote cost_currency_default, vat_rate, margin_percent and
    valid_until (= today + default_offer_validity_days). No-op when the company has no
    settings configured. Reads settings via a plain filter (no write on read).
    """
    # Every client КП is denominated in the national currency (UZS): the cost engine
    # converts each line (USD/EUR/…) to UZS, so subtotal/vat/total are stored in UZS.
    # Persist quote_currency=UZS so the value is EXPLICIT end-to-end (buyer view, PDF and
    # builder otherwise fall back to a guessed 'UZS'). Best-effort — skip silently if the
    # UZS lookup row isn't present (Currency is a lookup, not guaranteed on every env).
    if quote.quote_currency_id is None:
        from master_data.models import Currency

        uzs = Currency.objects.filter(code="UZS").first()
        if uzs is not None:
            quote.quote_currency_id = uzs.id
            quote.save(update_fields=["quote_currency", "updated_at"])

    if company is None:
        return quote
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import CompanySettings

    settings_row = CompanySettings.objects.filter(company=company).first()
    if settings_row is None:
        return quote

    changed = []
    if settings_row.default_delivery_basis_id and quote.delivery_basis_id is None:
        quote.delivery_basis_id = settings_row.default_delivery_basis_id
        changed.append("delivery_basis")
    if settings_row.default_cost_currency_id and quote.cost_currency_default_id is None:
        quote.cost_currency_default_id = settings_row.default_cost_currency_id
        changed.append("cost_currency_default")
    # vat_rate / margin_percent have non-null model defaults; only override when the
    # quote still carries the bare model default AND the company configured a value.
    if settings_row.default_vat_rate is not None and quote.vat_rate == Decimal("12.00"):
        quote.vat_rate = settings_row.default_vat_rate
        changed.append("vat_rate")
    if settings_row.default_margin_percent is not None and quote.margin_percent == Decimal("0"):
        quote.margin_percent = settings_row.default_margin_percent
        changed.append("margin_percent")
    if settings_row.default_offer_validity_days is not None and quote.valid_until is None:
        quote.valid_until = timezone.now().date() + timedelta(days=settings_row.default_offer_validity_days)
        changed.append("valid_until")

    if changed:
        quote.save(update_fields=[*changed, "updated_at"])
    return quote


def compute_default_valid_until(company: Optional[Company]):
    """The КП validity date derived from the company's ``default_offer_validity_days`` (Odoo
    Default Validity), or ``None`` when the company left it unconfigured. PURE — no writes.

    Used on SEND to populate a still-empty ``valid_until`` so every sent КП carries an expiry
    (the create-time pre-fill in ``apply_company_quote_defaults`` may not have run, or the
    setting was added after the КП was created). No hardcoded fallback: an unconfigured company
    yields ``None`` and the КП stays open-ended (today's public-link behaviour)."""
    if company is None:
        return None
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import CompanySettings

    settings_row = CompanySettings.objects.filter(company=company).first()
    if settings_row is None or settings_row.default_offer_validity_days is None:
        return None
    return timezone.now().date() + timedelta(days=settings_row.default_offer_validity_days)


def _has_legacy_send_role(actor, company_id: int) -> bool:
    """Transitional bridge (ADR-0005 Phase E U3): a member NOT yet migrated to a CompanyRole
    (company_role IS NULL) keeps send iff their legacy WorkspaceRole was OWNER or SALES_MANAGER —
    EXACTLY the pre-U3 gate, but scoped to un-migrated members only. This deliberately does NOT
    honour the bare can_sell capability (which defaults True), so a company_role-less member with
    a non-sales WorkspaceRole is not auto-granted a client-facing send. Dies once every member has
    a CompanyRole (invite / submit_company_profile / add_company_member all seed one)."""
    membership = (
        actor.memberships.filter(company_id=company_id, is_active=True, company_role__isnull=True)
        .select_related("role")
        .first()
    )
    return bool(
        membership
        and membership.role
        and membership.role.code in {WorkspaceRoleCode.OWNER, WorkspaceRoleCode.SALES_MANAGER}
    )


def can_send_quote_to_client(actor, quote) -> bool:
    """Who may push an internally-approved КП out to the client.

    The platform admin / superuser (escalation), or a member of the КП-owning company (the
    preparer's company that ran the approval chain) who holds the quote.send permission. Mirrors
    ADR-0002: the seller team builds AND sends its own quotes; sending is no longer
    platform-admin-only. The READY_TO_SEND status guard stays in send_to_client.

    ADR-0005 Phase E U3: gated on the INTENTIONAL quote.send CompanyRole permission
    (has_explicit_company_role_perm — fail-closed, no legacy can_sell auto-grant, so a member's
    default capability flag never promotes them to send a binding КП; mirrors the sibling
    client-facing gates contract.sign / payment.record). `_has_legacy_send_role` bridges members
    not yet migrated to a CompanyRole so no existing OWNER/SALES_MANAGER seller loses send
    mid-rollout. Client-facing send stays additionally gated by the paid-seller subscription
    (assert_seller_can_operate) and the quote.send entitlement in send_to_client.
    """
    if getattr(actor, "is_superuser", False) or getattr(actor, "is_platform_admin", False):
        return True
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return False
    return has_explicit_company_role_perm(actor, company_id, "quote.send") or _has_legacy_send_role(actor, company_id)


def can_duplicate_quote(actor, quote) -> bool:
    """Who may deep-copy a КП into a new DRAFT version (Odoo «Duplicate»).

    Duplicating BUILDS a new draft КП, so it is gated exactly like building — the superuser
    (platform escalation), or a member of the КП-owning company (the preparer's seller company)
    holding the ``quote.build`` CompanyRole permission. ``member_has_permission`` scopes to that
    owning company, which is BOTH the routing bind and the IDOR guard: a foreign seller (member
    of a different company, even one co-routed to the same deal) is not a member of the owning
    company → denied. A platform-admin VIEWER (SystemRole.ADMIN, no membership) is likewise
    denied — creating a КП is a business action they must not perform (ADMIN_VIEWER_CANNOT_ACT).
    """
    from accounts.services.permissions import member_has_permission

    if getattr(actor, "is_superuser", False):
        return True
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return False
    return member_has_permission(actor, company_id, "quote.build")


def approval_queue_for(user):
    """КП waiting on THIS user's pending approval STEP (unified step-based chain).

    A КП is in my queue when it is PENDING_APPROVAL, has a PENDING acting step at the
    CURRENT stage (lowest pending order), that step is in a company I belong to, and I hold
    the step's permission (quote.review for an intermediate, quote.approve_final for the head).
    """
    from accounts.constants import Permission
    from accounts.services.permissions import member_has_permission
    from crm.models import QuoteApprovalStep
    from crm.models.approvals import StepParticipation, StepStatus

    company_ids = set(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    if not company_ids:
        return Quote.objects.none()

    steps = (
        QuoteApprovalStep.objects.filter(
            status=StepStatus.PENDING, quote__status__code=QuoteStatusCode.PENDING_APPROVAL
        )
        .exclude(participation=StepParticipation.INFORMED)
        .select_related("quote", "quote__status", "quote__seller_company", "quote__prepared_by")
        .order_by("quote_id", "order")
    )
    active_order_by_quote: dict = {}
    actionable_quote_ids: set = set()
    for step in steps:
        quote = step.quote
        company_id = _quote_owner_company_id(quote)
        if company_id not in company_ids:
            continue
        # steps are ordered by order asc → the first seen for a quote is its active (min) order
        active = active_order_by_quote.setdefault(quote.id, step.order)
        if step.order != active:
            continue
        perm = (
            Permission.QUOTE_APPROVE_FINAL.value
            if step.participation == StepParticipation.HEAD
            else Permission.QUOTE_REVIEW.value
        )
        if member_has_permission(user, company_id, perm):
            actionable_quote_ids.add(quote.id)
    return (
        Quote.objects.filter(id__in=actionable_quote_ids)
        .select_related("deal", "deal__company", "status", "prepared_by")
        .order_by("-updated_at")
    )


# EXPIRED is a seeded QuoteStatus row (see the seed migration) but not a QuoteStatusCode
# workflow member — the expire_stale_quotes beat task keys on the same string literal.
_EXPIRED_STATUS_CODE = "EXPIRED"


def public_quote_gate(quote) -> Optional[str]:
    """Decide whether a КП is reachable via its PUBLIC (no-login) token link.

    Audit #17: the emailed public link had no TTL/revoke — it lived forever and ignored
    the КП's own validity. This is the single reachability gate the PublicQuoteView calls.
    Returns an error CODE (mapped to 404/410 by the view) or None when the link is live.

    Order matters: an unknown / not-yet-sent token is indistinguishable (404 NOT_FOUND, no
    info leak); a revoked or lapsed link is a definite 410 GONE.
    """
    from django.utils import timezone

    # Only a real, already-sent (frozen) КП was ever given a token. DRAFTs have none.
    if quote is None or quote.frozen_at is None:
        return "NOT_FOUND"
    if quote.public_token_revoked:
        return "QUOTE_LINK_REVOKED"
    # КП explicitly moved to EXPIRED (by the daily expire_stale_quotes task) → link is dead.
    if quote.status and quote.status.code == _EXPIRED_STATUS_CODE:
        return "QUOTE_LINK_EXPIRED"
    now = timezone.now()
    # valid_until is the КП's own validity date; a passed date closes the public link too.
    if quote.valid_until and quote.valid_until < now.date():
        return "QUOTE_LINK_EXPIRED"
    # Optional token-specific TTL (independent of valid_until); NULL = no separate TTL.
    if quote.public_token_expires_at and quote.public_token_expires_at < now:
        return "QUOTE_LINK_EXPIRED"
    return None
