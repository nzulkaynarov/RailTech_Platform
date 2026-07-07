from typing import Optional, Tuple

from django.db import transaction

from accounts.models import CustomUser
from core.audit import log_admin_action

from ..constants import ContractStatusCode, QuoteStatusCode
from ..models import ActivityLog, Quote

# ──────────────────────────────────────────────────────────────────────────
# Contracts
# ──────────────────────────────────────────────────────────────────────────


def _next_contract_number(seller_company=None) -> str:
    # Race-safe per-(company, year) counter (was count()+1 → duplicate-number 500 under
    # load). Carries the seller company so the contract gets THEIR prefix + counter.
    from .numbering import next_document_number

    return next_document_number("CT", "CT", company=seller_company)


def _cstatus(code: str):
    """Resolve a ContractStatus lookup row by code (F5.4 — status is a FK now).
    Raises if the code isn't seeded, surfacing a missing migration loudly (IRON RULE 1)."""
    from ..models import ContractStatus

    return ContractStatus.objects.get(code=code)


@transaction.atomic
def generate_contract_from_quote(
    quote_id: int,
    actor: Optional[CustomUser] = None,
    notes: str = "",
) -> Tuple[Optional["Contract"], Optional[str]]:  # noqa: F821
    """Create a Contract tied to an approved Quote, render its PDF."""
    from accounts.services import assert_seller_can_operate, is_platform_admin_viewer, is_seller

    from ..models import Contract

    if actor is not None and is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    # Generating the contract (from the approved КП) is a seller-side action.
    if actor is not None and not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    # Paid-seller gate: a seller without an operational subscription cannot transact.
    if actor is not None and (sub_err := assert_seller_can_operate(actor)):
        return None, sub_err
    quote = Quote.objects.select_related("deal__company", "status").get(pk=quote_id)

    if not quote.status or quote.status.code not in {QuoteStatusCode.APPROVED, QuoteStatusCode.SENT}:
        return None, "CONTRACT_NEEDS_APPROVAL"

    # Reuse existing draft contract if present
    contract = (
        Contract.objects.filter(deal=quote.deal, quote=quote)
        .exclude(
            status__code__in=[ContractStatusCode.CANCELLED],
        )
        .order_by("-created_at")
        .first()
    )

    if not contract:
        # Seller company = the КП author's owning company → its prefix + per-company counter.
        from .quotes import _quote_seller_company

        seller_company = _quote_seller_company(quote)
        contract = Contract(
            deal=quote.deal,
            quote=quote,
            number=_next_contract_number(seller_company),
            status=_cstatus(ContractStatusCode.DRAFT),
            total_amount=quote.total_incl_vat,
            currency=quote.items.first().frozen_currency if quote.items.exists() else None,
            created_by=actor,
            notes=notes,
        )
        contract.save()

    # F5.4: status is a FK lookup now. F1.6: render the PDF AFTER commit, off the
    # request thread — rendering inside this atomic block wrote the file to storage
    # even when a later step rolled the transaction back, orphaning it. on_commit
    # fires only on success; the download endpoint renders lazily if this races behind.
    if contract.status_code == ContractStatusCode.DRAFT:
        contract.status = _cstatus(ContractStatusCode.PENDING_CLIENT)
    contract.save(update_fields=["status", "updated_at"])

    from ..tasks import render_document_pdf

    contract_id = contract.id
    transaction.on_commit(lambda: render_document_pdf.delay("contract", contract_id))

    ActivityLog.objects.create(
        action="Создан контракт",
        detail=f"Контракт {contract.number} по сделке #{quote.deal_id}",
        user=actor,
        level="INFO",
        deal=quote.deal,
        company_id=quote.deal.company_id,
    )
    # P1: a created contract must not be silent — tell BOTH parties it awaits signature
    # (previously generate set PENDING_CLIENT and nobody was notified → dead-end after accept).
    _notify_contract_pending(contract)
    return contract, None


def _notify_contract_pending(contract) -> None:
    """Notify both parties that a contract is awaiting signature (PENDING_CLIENT)."""
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    info = NotificationType.objects.filter(code="INFO").first()
    # N2: the contract needs BOTH signatures (client + seller), so at PENDING_CLIENT each party's
    # OWN signature is what's outstanding — say «требуется ВАША подпись» per recipient instead of
    # the ambiguous «требуется подпись сторон» (which left neither side knowing who has to act).
    deal_ref = contract.deal.title or f"#{contract.deal_id}"
    for recipient in {contract.deal.client, _contract_seller_recipient(contract)}:
        if recipient is None:
            continue
        notif = Notification.objects.create(
            user=recipient,
            type=info,
            title="Требуется ваша подпись",
            message=f"Контракт {contract.number} по сделке «{deal_ref}» готов — требуется ваша подпись.",
            link="/crm/deals",
            deal=contract.deal,
        )
        push_notification_ws(notif)


def _render_contract_pdf(contract) -> None:
    from io import BytesIO

    from django.core.files.base import ContentFile
    from django.template.loader import render_to_string
    from weasyprint import HTML

    # Supplier party = the company that OWNS the КП (authoritative — from the quote, not
    # a preparer's primary membership which can be missing/wrong), plus its branded
    # document profile (legal name + requisites), mirroring the КП PDF. NEVER a hardcoded
    # platform identity: a contract is a legal document and must name the real counterparty.
    from .quotes import _quote_seller_company, _seller_document_profile

    supplier = _quote_seller_company(contract.quote)
    seller_profile = _seller_document_profile(supplier)

    html_string = render_to_string(
        "crm/contract_pdf.html",
        {
            "contract": contract,
            "deal": contract.deal,
            "company": contract.deal.company,
            "supplier": supplier,
            "seller_profile": seller_profile,
            "quote": contract.quote,
            "items": contract.quote.items.select_related("product", "frozen_currency").all(),
        },
    )
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    filename = f"Contract_{contract.number}.pdf"
    contract.pdf_file.save(filename, ContentFile(buf.getvalue()), save=True)


@transaction.atomic
def sign_contract_by_client(
    contract_id: int,
    client_user: CustomUser,
) -> Tuple[Optional["Contract"], Optional[str]]:  # noqa: F821
    """Click-to-sign by client. MANUAL MODE — to be replaced by E-IMZO/DocuSign.
    See memory `tech_debt_payment_esign.md`.
    """
    from django.utils import timezone

    from accounts.services import is_member_of, is_platform_admin_viewer

    from ..models import Contract

    contract = Contract.objects.select_for_update().select_related("deal").get(pk=contract_id)
    if is_platform_admin_viewer(client_user):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    # Additive guard (defense-in-depth): legacy can_buy capability OR explicit
    # contract.sign CompanyRole permission. has_explicit_company_role_perm skips
    # the legacy can_buy fallback so only members with an intentional CompanyRole
    # assignment pass through this new path (no accidental promotion).
    from ._params import has_explicit_company_role_perm

    if not (
        getattr(client_user, "is_superuser", False)
        or is_member_of(client_user, contract.deal.company_id, capability="buy")
        or has_explicit_company_role_perm(client_user, contract.deal.company_id, "contract.sign")
    ):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if contract.status_code not in {ContractStatusCode.DRAFT, ContractStatusCode.PENDING_CLIENT}:
        return None, "CONTRACT_CLIENT_SIGN_NOT_ALLOWED"
    contract.client_signer = client_user
    contract.client_signed_at = timezone.now()
    contract.status = _cstatus(
        ContractStatusCode.SIGNED if contract.manager_signed_at else ContractStatusCode.PENDING_MANAGER
    )
    contract.save(update_fields=["client_signer", "client_signed_at", "status", "updated_at"])
    ActivityLog.objects.create(
        action="[MANUAL_MODE] Подписан контракт (сторона клиента)",
        detail=f"Контракт {contract.number} / сделка #{contract.deal_id}",
        user=client_user,
        level="INFO",
        deal=contract.deal,
        company_id=contract.deal.company_id,
    )
    _finalize_if_signed(contract)
    return contract, None


@transaction.atomic
def sign_contract_by_manager(
    contract_id: int,
    manager_user: CustomUser,
) -> Tuple[Optional["Contract"], Optional[str]]:  # noqa: F821
    """Click-to-sign by seller-side company manager. MANUAL MODE — to be replaced by E-IMZO.
    See memory `tech_debt_payment_esign.md`.

    Seller side is represented by any member with can_sell on the deal.company
    itself (self-service intra-company deals).
    """
    from django.utils import timezone

    from accounts.services import (
        assert_seller_can_operate,
        is_platform_admin_viewer,
        is_seller,
        seller_company_routed_to_deal,
    )

    from ..models import Contract

    contract = Contract.objects.select_for_update().select_related("deal").get(pk=contract_id)
    if is_platform_admin_viewer(manager_user):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    # Seller side signs as "manager". Single-seller model: any can_sell member
    # (RailTech). The accepted-bid-supplier check is subsumed by is_seller — a
    # winning supplier's member also carries can_sell.
    # Additive guard (defense-in-depth): legacy is_seller() OR explicit contract.sign
    # CompanyRole permission in any active SELLER-type company membership.
    # has_explicit_company_role_perm skips the legacy fallback so only members with
    # an intentional CompanyRole assignment pass through this new path.
    from accounts.constants import SELLER_COMPANY_TYPES

    from ._params import has_explicit_company_role_perm

    seller_memberships = manager_user.memberships.filter(
        is_active=True, company__types__code__in=SELLER_COMPANY_TYPES
    ).only("company_id")
    has_contract_sign_perm = any(
        has_explicit_company_role_perm(manager_user, m.company_id, "contract.sign") for m in seller_memberships
    )
    # Bind to THIS contract's deal routing — any seller could otherwise sign a competitor's
    # contract by enumerating ids (audit H3).
    if not (
        getattr(manager_user, "is_superuser", False)
        or (
            (is_seller(manager_user) or has_contract_sign_perm)
            and seller_company_routed_to_deal(manager_user, contract.deal_id)
        )
    ):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    # Paid-seller gate: signing commits the seller — requires an active subscription.
    if sub_err := assert_seller_can_operate(manager_user):
        return None, sub_err
    if contract.status_code not in {
        ContractStatusCode.DRAFT,
        ContractStatusCode.PENDING_MANAGER,
        ContractStatusCode.PENDING_CLIENT,
    }:
        return None, "CONTRACT_MANAGER_SIGN_NOT_ALLOWED"
    contract.manager_signer = manager_user
    contract.manager_signed_at = timezone.now()
    contract.status = _cstatus(
        ContractStatusCode.SIGNED if contract.client_signed_at else ContractStatusCode.PENDING_CLIENT
    )
    contract.save(update_fields=["manager_signer", "manager_signed_at", "status", "updated_at"])
    ActivityLog.objects.create(
        action="[MANUAL_MODE] Подписан контракт (сторона RailTech)",
        detail=f"Контракт {contract.number} / сделка #{contract.deal_id}",
        user=manager_user,
        level="INFO",
        deal=contract.deal,
        company_id=contract.deal.company_id,
    )
    _finalize_if_signed(contract)
    return contract, None


def _contract_seller_recipient(contract):
    """The seller-side человек to notify about a contract — the КП author (prepared_by), NOT the
    legacy NULL deal.manager that the old notifications targeted (so the author silently never
    learned the contract was signed / the КП expired). P0/P1 loop fix."""
    quote = getattr(contract, "quote", None)
    return getattr(quote, "prepared_by", None) if quote else None


def _finalize_if_signed(contract) -> None:
    """When BOTH parties have signed, close the loop: auto-advance the deal CONTRACT_SIGNED →
    CLOSED_WON (the contract gate is now satisfied; this also triggers the auto-invoice hook —
    the loop's finish line) and notify both sides. Previously the contract sat SIGNED while the
    deal stayed in CONTRACT_SIGNED forever and the author was never told (dead-end)."""
    if contract.status_code != ContractStatusCode.SIGNED:
        return
    from ..constants import DealStageCode
    from .deals import transition_deal_stage

    # actor=None → internal/system transition (bypasses the admin-viewer actor-guard, logs as auto).
    _, err = transition_deal_stage(
        contract.deal, DealStageCode.CLOSED_WON, actor=None, reason="Контракт подписан обеими сторонами"
    )
    if err:
        # The signature itself succeeded; a stage hiccup must not break it — record, don't raise.
        ActivityLog.objects.create(
            action="Авто-переход в CLOSED_WON не выполнен",
            detail=f"Контракт {contract.number} / сделка #{contract.deal_id}: {err}",
            level="WARNING",
            deal=contract.deal,
            company_id=contract.deal.company_id,
        )
    _notify_contract_signed(contract)


def _notify_contract_signed(contract) -> None:
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    if contract.status_code != ContractStatusCode.SIGNED:
        return
    info = NotificationType.objects.filter(code="SUCCESS").first()
    for recipient in {contract.deal.client, _contract_seller_recipient(contract)}:
        if recipient is None:
            continue
        notif = Notification.objects.create(
            user=recipient,
            type=info,
            title="Контракт подписан",
            message=f"Контракт {contract.number} по сделке #{contract.deal_id} подписан обеими сторонами",
            link="/crm/deals",
            deal=contract.deal,
        )
        push_notification_ws(notif)  # realtime, not just the 60s poll


@transaction.atomic
def cancel_contract(
    contract_id: int, actor: CustomUser, reason: str = ""
) -> Tuple[Optional["Contract"], Optional[str]]:  # noqa: F821
    from accounts.services import is_platform_admin_viewer

    from ..models import Contract

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    contract = Contract.objects.select_for_update().get(pk=contract_id)
    if contract.status_code == ContractStatusCode.SIGNED:
        return None, "CONTRACT_SIGNED_CANNOT_CANCEL"
    contract.status = _cstatus(ContractStatusCode.CANCELLED)
    contract.notes = f"{contract.notes}\nОтменён {actor}: {reason}".strip()
    contract.save(update_fields=["status", "notes", "updated_at"])
    return contract, None


@transaction.atomic
def force_cancel_contract(
    contract_id: int,
    admin_user: CustomUser,
    reason: str = "",
) -> Tuple[Optional["Contract"], Optional[str]]:  # noqa: F821
    """Platform-admin force override: cancel a contract regardless of its status.

    Used for escalations (e.g. fraud, court order, mutual annulment after signing).
    Logged with [FORCE_ADMIN] marker. Reason is mandatory for audit. Viewer-mode
    admins are permitted — force-actions are platform-admin moderation, not bound
    to a CompanyMember.
    """
    from ..models import Contract

    if not (getattr(admin_user, "is_superuser", False) or (admin_user.role and admin_user.role.code == "ADMIN")):
        return None, "PLATFORM_ADMIN_REQUIRED"
    if not reason.strip():
        return None, "FORCE_REASON_REQUIRED"
    contract = Contract.objects.select_for_update().get(pk=contract_id)
    old_status = contract.status_code
    contract.status = _cstatus(ContractStatusCode.CANCELLED)
    contract.notes = (
        f"{contract.notes}\n[FORCE_ADMIN] {admin_user.email}: {reason}"
        if contract.notes
        else f"[FORCE_ADMIN] {admin_user.email}: {reason}"
    )
    contract.save(update_fields=["status", "notes", "updated_at"])
    # Structured, entity-scoped audit (G2 Gap A) — route through log_admin_action so the
    # override carries reason + entity_type/id + before/after and surfaces on the contract
    # timeline and the «Журнал доступа» page (not a bare, unscoped ActivityLog).
    log_admin_action(
        entity_type="contract",
        entity_id=contract_id,
        action="[FORCE_ADMIN] Контракт отменён платформенным админом",
        detail=f"Контракт #{contract_id} ({old_status} → CANCELLED).",
        actor=admin_user,
        reason=reason,
        before={"status": old_status},
        after={"status": ContractStatusCode.CANCELLED},
        level="WARNING",
        deal_id=contract.deal_id,
        company_id=contract.deal.company_id,
    )
    return contract, None
