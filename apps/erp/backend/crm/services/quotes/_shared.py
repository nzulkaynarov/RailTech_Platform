"""Shared low-level КП helpers used across the quotes service submodules.

These are leaf helpers (company resolution, document-profile branding, status
mutation, notifications, activity logging) with no dependency on the sibling
pricing / access / lifecycle / bulk submodules — so importing them never risks a
circular import. Kept private (leading underscore) except where re-exported by the
package ``__init__`` for the historical public import surface.
"""

from typing import Optional, Tuple

from accounts.models import Company, CompanyMember
from crm.constants import QuoteStatusCode
from crm.models import ActivityLog, QuoteStatus


def _quote_owner_company_id(quote) -> Optional[int]:
    """Company that owns the КП — the seller team that runs the approval chain and whose
    requisites brand the document.

    Source of truth is the explicit `Quote.seller_company` FK, set at build/claim time to the
    VERIFIED routed seller (audit F0/H2). Read FIRST so the role checks, ВЭД/director gate,
    auto-split, PDF header and КП-number minting all resolve to ONE coherent company — never
    "validate against routed company B but anchor to the preparer's primary company A".
    Falls back to the preparer's primary membership ONLY for legacy quotes saved before the FK
    existed. None if neither is resolvable (unclaimed buyer request)."""
    if quote.seller_company_id:
        return quote.seller_company_id
    if not quote.prepared_by_id:
        return None
    membership = (
        CompanyMember.objects.filter(user_id=quote.prepared_by_id, is_primary=True, is_active=True)
        .only("company_id")
        .first()
    )
    return membership.company_id if membership else None


def _quote_seller_company(quote):
    """The issuing (seller) Company for the КП document header — the preparer's
    owning company. None when the КП is still an unclaimed buyer request (no preparer),
    in which case the PDF header falls back to the platform name."""
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return None
    return Company.objects.filter(pk=company_id).first()


def _quote_client_display_name(quote) -> str:
    """Human label for the КП's CLIENT side, safe when `deal.company` is NULL.

    Wave E F3 made `Deal.company` nullable (company-less «калькулятор» draft), so
    `quote.deal.company.name` is no longer safe in notification/audit strings. Degrades:
    client company → offline contact name → registered client's name → a generic label.
    Never raises, never returns an empty string.
    """
    deal = quote.deal
    company = getattr(deal, "company", None)
    if company is not None and (company.name or "").strip():
        return company.name.strip()
    contact = getattr(deal, "contact", None)
    if contact is not None and (contact.name or "").strip():
        return contact.name.strip()
    client = getattr(deal, "client", None)
    if client is not None:
        label = (client.get_full_name() or client.email or "").strip()
        if label:
            return label
    return "Клиент"


def _seller_document_profile(seller_company):
    """The selling company's branded document requisites for the КП header — or None.

    Only returns a profile when the seller has actually filled it in (at least a legal
    name or a logo); an empty auto-created profile yields None so the template cleanly
    falls back to the seller Company fields / platform name. Read-only — never creates.
    """
    from accounts.models import CompanyDocumentProfile

    if seller_company is None:
        return None
    profile = CompanyDocumentProfile.objects.filter(company=seller_company).first()
    return profile if _profile_has_branding(profile) else None


def _profile_has_branding(profile) -> bool:
    """True if the document profile has actual branding filled in (legal name / logo / bank
    requisites) — the single predicate deciding whether the «Поставщик» block renders from the
    profile or falls back to the Company. Shared with documents.document_brand_context so the two
    never drift. The layout toggles are independent of this — they always apply."""
    if profile is None:
        return False
    return bool((profile.legal_name or "").strip() or profile.logo or (profile.bank_details or "").strip())


def _set_quote_status(quote, code: str) -> None:
    # .get (not get_or_create): the status MUST exist from the seed migration.
    quote.status = QuoteStatus.objects.get(code=code)
    fields = ["status", "updated_at"]
    if code == QuoteStatusCode.DRAFT and quote.fx_fixed_at is not None:
        # M1-ERP-08: КП вернулось в черновик — курс снова живой (sales.services.quote_fx).
        quote.fx_fixed_at = None
        fields.append("fx_fixed_at")
    quote.save(update_fields=fields)


def _notify_quote_outcome(
    quote, *, type_code: str, title: str, message: str, event_code: str = "", event_params: dict | None = None
) -> None:
    """Tell the seller side a client decided on a КП (approved/rejected).

    Targets the КП author `prepared_by` (reliably set) plus a distinct
    `deal.manager` if one is assigned — in the single-seller model deal.manager
    is usually empty, so the old manager-only notification never reached anyone.
    Pushed over WS via push_notification_ws for realtime delivery.
    """
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    recipient_ids = {quote.prepared_by_id, quote.deal.manager_id} - {None}
    if not recipient_ids:
        return
    ntype = NotificationType.objects.filter(code=type_code).first()
    for uid in recipient_ids:
        notif = Notification.objects.create(
            user_id=uid,
            type=ntype,
            title=title,
            message=message,
            link="/crm/deals",
            deal=quote.deal,
            event_code=event_code,
            event_params=event_params or {},
        )
        push_notification_ws(notif)


def _log_quote(
    quote,
    actor,
    action: str,
    detail: str = "",
    *,
    event_code: str = "",
    event_params: Optional[dict] = None,
) -> None:
    ActivityLog.objects.create(
        action=action,
        detail=detail,
        user=actor,
        level="INFO",
        entity_type="quote",
        entity_id=quote.id,
        deal_id=quote.deal_id,
        company_id=quote.deal.company_id if quote.deal_id else None,
        event_code=event_code,
        event_params=event_params or {},
    )


def resolve_quote_recipient(quote) -> Optional[Tuple[str, str]]:
    """The КП's outgoing email recipient as ``(email, display_name)``, or ``None``.

    SINGLE source of truth for "does this КП have someone to send to", shared by the
    synchronous RECIPIENT_REQUIRED gate in ``send_to_client`` and the async
    ``crm.tasks.send_quote_email`` task (B5). They MUST agree: when they drifted, the task
    silently skipped the email while the КП was already marked SENT — «отправлено в никуда».

    Registered buyer (``deal.client``) wins over the offline contact (``deal.contact``),
    matching the unified-send rule: one action, channel adapts to who the recipient is.
    """
    deal = quote.deal
    client = getattr(deal, "client", None)
    if client and client.email:
        return client.email, (client.get_full_name() or client.email)
    contact = getattr(deal, "contact", None)
    if contact and contact.email:
        return contact.email, contact.name
    return None
