from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Tuple

from django.db import models, transaction
from django.db.models import Count, Q, Sum

from accounts.constants import SystemRoleCode, VerificationStatusCode, WorkspaceRoleCode
from accounts.models import Company, CompanyMember, CustomUser
from accounts.services.permissions import has_workspace_role

from ..constants import DealStageCode, QuoteStatusCode
from ..models import ActivityLog, Deal, Quote, QuoteItem, QuoteItemHistory, QuoteStatus
from .deals import transition_deal_stage


def _quote_owner_company_id(quote) -> Optional[int]:
    """Company that owns the КП — the preparer's primary company (the seller team
    that runs the approval chain). None if the quote has no preparer yet."""
    if not quote.prepared_by_id:
        return None
    membership = (
        CompanyMember.objects.filter(user_id=quote.prepared_by_id, is_primary=True, is_active=True)
        .only("company_id")
        .first()
    )
    return membership.company_id if membership else None


def _set_quote_status(quote, code: str) -> None:
    # .get (not get_or_create): the status MUST exist from the seed migration.
    quote.status = QuoteStatus.objects.get(code=code)
    quote.save(update_fields=["status", "updated_at"])


def _notify_quote_outcome(quote, *, type_code: str, title: str, message: str) -> None:
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
            user_id=uid, type=ntype, title=title, message=message, link="/crm/deals", deal=quote.deal
        )
        push_notification_ws(notif)


def _log_quote(quote, actor, action: str, detail: str = "") -> None:
    ActivityLog.objects.create(
        action=action,
        detail=detail,
        user=actor,
        level="INFO",
        entity_type="quote",
        entity_id=quote.id,
    )


# Which КП statuses each WorkspaceRole is responsible for advancing — drives the
# per-role "my approval queue".
_ROLE_QUEUE_STATUSES = {
    WorkspaceRoleCode.SALES_MANAGER: {QuoteStatusCode.DRAFT},
    WorkspaceRoleCode.FOREIGN_TRADE_SPECIALIST: {QuoteStatusCode.PENDING_TRADE_REVIEW},
    WorkspaceRoleCode.DIRECTOR: {QuoteStatusCode.PENDING_APPROVAL},
    WorkspaceRoleCode.OWNER: {
        QuoteStatusCode.DRAFT,
        QuoteStatusCode.PENDING_TRADE_REVIEW,
        QuoteStatusCode.PENDING_APPROVAL,
        QuoteStatusCode.READY_TO_SEND,
    },
}


def can_send_quote_to_client(actor, quote) -> bool:
    """Who may push an internally-approved КП out to the client.

    The platform admin / superuser (escalation), or the SALES_MANAGER / OWNER of
    the company that owns the КП (the preparer's company that ran the approval
    chain). Mirrors ADR-0002: the seller team builds AND sends its own quotes;
    sending is no longer platform-admin-only. The READY_TO_SEND status guard
    itself stays in QuoteLifecycleService.send_to_client.
    """
    if getattr(actor, "is_superuser", False) or getattr(actor, "is_platform_admin", False):
        return True
    company_id = _quote_owner_company_id(quote)
    if not company_id:
        return False
    # has_workspace_role already lets OWNER through as the escape hatch.
    return has_workspace_role(actor, company_id, [WorkspaceRoleCode.SALES_MANAGER])


def approval_queue_for(user):
    """КП waiting on this user's workspace-role step, scoped to the user's own
    companies. Each (company, role) the user holds contributes only the statuses
    that role advances — so a SALES_MANAGER in company A never sees company A's
    director-stage quotes unless they are also OWNER/DIRECTOR there."""
    memberships = user.memberships.filter(is_active=True).select_related("role")
    condition = Q()
    matched = False
    for membership in memberships:
        if not membership.role:
            continue
        statuses = _ROLE_QUEUE_STATUSES.get(membership.role.code)
        if not statuses:
            continue
        matched = True
        condition |= Q(
            prepared_by__memberships__company_id=membership.company_id,
            prepared_by__memberships__is_primary=True,
            prepared_by__memberships__is_active=True,
            status__code__in=statuses,
        )
    if not matched:
        return Quote.objects.none()
    return (
        Quote.objects.filter(condition)
        .select_related("deal", "deal__company", "status", "prepared_by")
        .distinct()
        .order_by("-updated_at")
    )


class QuoteCalculationService:
    """
    Centralized engine for financial calculations.
    Ensures consistency between QuoteItems and Quote totals.
    """

    @staticmethod
    def calculate_item_prices(item: QuoteItem, commit=True):
        """
        Calculates Landed Cost and Final Price for a single item.
        Formula:
          1. landed_cost = base + logistics + customs
          2. final_price = landed_cost * (1 + margin%)
        """
        is_service = item.product and item.product.domain_type and item.product.domain_type.code == "SERVICES"

        if is_service:
            item.landed_cost = item.frozen_base_price
            item.logistics_cost = Decimal("0")
            item.customs_duty = Decimal("0")
        else:
            item.landed_cost = item.frozen_base_price + item.logistics_cost + item.customs_duty

        margin_mult = Decimal("1") + (item.margin_percent / Decimal("100"))
        item.final_price_excl_vat = (item.landed_cost * margin_mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if commit:
            item.save(update_fields=["landed_cost", "final_price_excl_vat", "logistics_cost", "customs_duty"])

        return item

    @classmethod
    @transaction.atomic
    def recalculate_quote(cls, quote_id: int):
        """
        Full recalculation of a Quote and all its items.
        Prevents N+1 updates by using aggregation.
        """
        quote = Quote.objects.select_for_update().get(pk=quote_id)
        items = list(quote.items.select_related("product__domain_type").all())

        # 1. Recalculate each item price (without saving each time to DB yet)
        for item in items:
            cls.calculate_item_prices(item, commit=False)

        # 2. Bulk update items to minimize DB hits
        QuoteItem.objects.bulk_update(items, ["landed_cost", "final_price_excl_vat", "logistics_cost", "customs_duty"])

        # 2b. Record audit trail snapshots for changed items
        history_records = [
            QuoteItemHistory(
                quote_item=item,
                frozen_base_price=item.frozen_base_price,
                logistics_cost=item.logistics_cost,
                customs_duty=item.customs_duty,
                margin_percent=item.margin_percent,
                landed_cost=item.landed_cost,
                final_price_excl_vat=item.final_price_excl_vat,
                quantity=item.quantity,
                change_reason="recalculation",
            )
            for item in items
        ]
        if history_records:
            QuoteItemHistory.objects.bulk_create(history_records)

        # 3. Aggregation for Quote totals (use QuerySet, not list)
        totals = quote.items.aggregate(subtotal=models.Sum(models.F("final_price_excl_vat") * models.F("quantity")))

        subtotal = totals["subtotal"] or Decimal("0")
        vat_rate = quote.vat_rate / Decimal("100")

        penny = Decimal("0.01")
        quote.subtotal_excl_vat = subtotal.quantize(penny, rounding=ROUND_HALF_UP)
        quote.vat_amount = (subtotal * vat_rate).quantize(penny, rounding=ROUND_HALF_UP)
        quote.total_incl_vat = quote.subtotal_excl_vat + quote.vat_amount

        quote.save(update_fields=["subtotal_excl_vat", "vat_amount", "total_incl_vat", "updated_at"])
        return quote


def get_crm_analytics_data():
    """LOW-4: Extracted analytics logic from views to service."""
    deals = Deal.objects.all()
    items = QuoteItem.objects.all()

    pipeline_by_status = list(deals.values("stage__name").annotate(count=Count("id")))
    sourcing_backlog = items.filter(product__isnull=True).count()

    total_items = items.count()
    mapped_items = items.filter(product__isnull=False).count()
    mapped_items_percentage = (mapped_items / total_items * 100) if total_items > 0 else 0

    kyc_backlog = Company.objects.filter(
        verification_status__code__in=[VerificationStatusCode.L1_UNVERIFIED, VerificationStatusCode.PROFILE_SUBMITTED]
    ).count()

    total_pipeline_value = (
        Quote.objects.filter(status__code__in=[QuoteStatusCode.SENT, QuoteStatusCode.APPROVED]).aggregate(
            total=Sum("total_incl_vat")
        )["total"]
        or 0
    )

    return {
        "pipeline_by_status": pipeline_by_status,
        "sourcing_backlog": sourcing_backlog,
        "kyc_backlog": kyc_backlog,
        "total_pipeline_value": float(total_pipeline_value),
        "mapped_items_percentage": round(mapped_items_percentage, 1),
    }


class QuoteLifecycleService:
    """Manages Quote state transitions: generate PDF, send, approve, reject."""

    @staticmethod
    @transaction.atomic
    def generate_pdf(quote_id: int) -> Quote:
        """Generate PDF for a quote using WeasyPrint."""
        from io import BytesIO

        from django.core.files.base import ContentFile
        from django.template.loader import render_to_string
        from weasyprint import HTML

        quote = (
            Quote.objects.select_related("deal__company", "status", "tax_country", "prepared_by")
            .prefetch_related("items__product__domain_type")
            .get(pk=quote_id)
        )

        html_string = render_to_string(
            "crm/quote_pdf.html",
            {
                "quote": quote,
                "items": quote.items.select_related("product", "frozen_currency").all(),
                "company": quote.deal.company,
            },
        )

        pdf_file = BytesIO()
        HTML(string=html_string).write_pdf(pdf_file)

        filename = f"KP_{quote.deal.company.inn}_{quote.deal_id}_v{quote.version}.pdf"
        quote.pdf_file.save(filename, ContentFile(pdf_file.getvalue()), save=True)

        return quote

    @staticmethod
    @transaction.atomic
    def send_to_client(quote_id: int, sent_by_user) -> Quote:
        """
        Send quote to client:
        1. Guard: only READY_TO_SEND (internally approved) quotes can be sent
        2. Generate PDF if not exists
        3. Set frozen_at timestamp
        4. Change status to SENT
        5. Change deal stage to QUOTE_SENT via FSM
        6. Create notification for client
        """
        from django.utils import timezone

        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related("deal__company", "deal__client", "deal__stage", "status").get(pk=quote_id)

        # Status guard: only an internally-approved КП (READY_TO_SEND — it passed
        # the sales → ВЭД → director chain) may go out to the client.
        current = quote.status.code if quote.status else "None"
        if current != QuoteStatusCode.READY_TO_SEND:
            raise ValueError(
                f"Cannot send quote in status '{current}'. "
                "Only READY_TO_SEND quotes (internally approved) can be sent to the client."
            )

        # Render the PDF off the request thread, after commit (F1.6) — rendering it
        # synchronously here wrote the file inside this atomic block, orphaning it if a
        # later step rolled back. The client opens the КП via export-pdf, which renders
        # lazily if this task hasn't finished yet.
        if not quote.pdf_file:
            from ..tasks import render_document_pdf

            transaction.on_commit(lambda: render_document_pdf.delay("quote", quote_id))

        # Freeze prices
        sent_status = QuoteStatus.objects.filter(code=QuoteStatusCode.SENT).first()
        quote.status = sent_status
        quote.frozen_at = timezone.now()
        quote.save(update_fields=["status", "frozen_at", "updated_at"])

        # Change deal stage via FSM
        transition_deal_stage(
            quote.deal,
            DealStageCode.QUOTE_SENT,
            actor=sent_by_user,
            reason=f"КП v{quote.version} отправлено клиенту",
        )

        # Create notification for client contact
        if quote.deal.client:
            info_type = NotificationType.objects.filter(code="INFO").first()
            Notification.objects.create(
                user=quote.deal.client,
                type=info_type,
                title="Новое коммерческое предложение",
                message=f"Вам отправлено КП v{quote.version} по сделке #{quote.deal_id}",
                link="/cabinet/deals",
                deal=quote.deal,
            )

        return quote

    @staticmethod
    @transaction.atomic
    def approve_quote(quote_id: int, approved_by_user) -> Quote:
        """Client approves the quote. Only SENT quotes can be approved."""
        from django.utils import timezone

        quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else "None"
        if current != QuoteStatusCode.SENT:
            raise ValueError(f"Cannot approve quote in status '{current}'. " "Only SENT quotes can be approved.")

        approved_status = QuoteStatus.objects.filter(code=QuoteStatusCode.APPROVED).first()
        quote.status = approved_status
        quote.approved_at = timezone.now()
        quote.approved_by = approved_by_user
        quote.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])

        # Change deal stage via FSM
        transition_deal_stage(
            quote.deal,
            DealStageCode.CONTRACT_SIGNED,
            actor=approved_by_user,
            reason=f"КП v{quote.version} одобрено клиентом",
        )

        # Notify the seller who built the КП (and a distinct manager, if assigned)
        # that the client approved. deal.manager is usually unset in the single-
        # seller model, so prepared_by is the reliable recipient — without it the
        # seller never learned the outcome. Pushed over WS for realtime delivery.
        _notify_quote_outcome(
            quote,
            type_code="SUCCESS",
            title="КП одобрено клиентом",
            message=f"{quote.deal.company.name} одобрил КП v{quote.version}",
        )

        return quote

    # ── Internal approval chain (документооборот) ──────────────────────────
    # DRAFT → PENDING_TRADE_REVIEW → PENDING_APPROVAL → READY_TO_SEND → (send).
    # Each step is gated by the actor's WorkspaceRole in the company that owns the
    # КП (the preparer's company); OWNER may act on any step. Returns
    # (quote, None) on success or (None, error_code) for views to map to HTTP.

    @staticmethod
    @transaction.atomic
    def submit_for_review(quote_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str]]:
        """Sales submits a built КП into the chain. DRAFT → PENDING_TRADE_REVIEW,
        or straight to PENDING_APPROVAL if the company has no ВЭД member."""
        quote = Quote.objects.select_related("status", "prepared_by").get(pk=quote_id)
        # The submitter anchors the owning company if no preparer is recorded yet.
        if not quote.prepared_by_id:
            quote.prepared_by = actor
            quote.save(update_fields=["prepared_by", "updated_at"])
        company_id = _quote_owner_company_id(quote)
        if not company_id:
            return None, "NO_QUOTE_COMPANY"
        if not has_workspace_role(actor, company_id, [WorkspaceRoleCode.SALES_MANAGER]):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != QuoteStatusCode.DRAFT:
            return None, "INVALID_STATUS"
        has_trade = CompanyMember.objects.filter(
            company_id=company_id, is_active=True, role__code=WorkspaceRoleCode.FOREIGN_TRADE_SPECIALIST
        ).exists()
        next_code = QuoteStatusCode.PENDING_TRADE_REVIEW if has_trade else QuoteStatusCode.PENDING_APPROVAL
        _set_quote_status(quote, next_code)
        _log_quote(quote, actor, "quote.submit_for_review", f"КП v{quote.version} на согласование → {next_code}")
        return quote, None

    @staticmethod
    @transaction.atomic
    def confirm_trade_review(quote_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str]]:
        """ВЭД confirms. PENDING_TRADE_REVIEW → PENDING_APPROVAL."""
        quote = Quote.objects.select_related("status", "prepared_by").get(pk=quote_id)
        company_id = _quote_owner_company_id(quote)
        if not company_id:
            return None, "NO_QUOTE_COMPANY"
        if not has_workspace_role(actor, company_id, [WorkspaceRoleCode.FOREIGN_TRADE_SPECIALIST]):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != QuoteStatusCode.PENDING_TRADE_REVIEW:
            return None, "INVALID_STATUS"
        _set_quote_status(quote, QuoteStatusCode.PENDING_APPROVAL)
        _log_quote(
            quote, actor, "quote.confirm_trade_review", f"КП v{quote.version} подтверждено ВЭД → PENDING_APPROVAL"
        )
        return quote, None

    @staticmethod
    @transaction.atomic
    def director_approve(quote_id: int, actor: CustomUser) -> Tuple[Optional[Quote], Optional[str]]:
        """Director approves internally. PENDING_APPROVAL → READY_TO_SEND."""
        quote = Quote.objects.select_related("status", "prepared_by").get(pk=quote_id)
        company_id = _quote_owner_company_id(quote)
        if not company_id:
            return None, "NO_QUOTE_COMPANY"
        if not has_workspace_role(actor, company_id, [WorkspaceRoleCode.DIRECTOR]):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != QuoteStatusCode.PENDING_APPROVAL:
            return None, "INVALID_STATUS"
        _set_quote_status(quote, QuoteStatusCode.READY_TO_SEND)
        _log_quote(quote, actor, "quote.director_approve", f"КП v{quote.version} утверждено директором → READY_TO_SEND")
        return quote, None

    @staticmethod
    @transaction.atomic
    def send_back(quote_id: int, actor: CustomUser, reason: str = "") -> Tuple[Optional[Quote], Optional[str]]:
        """Return a КП under review to sales for rework. Any review status → DRAFT.
        Allowed for ВЭД, DIRECTOR (and OWNER)."""
        quote = Quote.objects.select_related("status", "prepared_by").get(pk=quote_id)
        company_id = _quote_owner_company_id(quote)
        if not company_id:
            return None, "NO_QUOTE_COMPANY"
        if not has_workspace_role(
            actor, company_id, [WorkspaceRoleCode.FOREIGN_TRADE_SPECIALIST, WorkspaceRoleCode.DIRECTOR]
        ):
            return None, "ROLE_NOT_PERMITTED"
        review_states = {
            QuoteStatusCode.PENDING_TRADE_REVIEW,
            QuoteStatusCode.PENDING_APPROVAL,
            QuoteStatusCode.READY_TO_SEND,
        }
        if not quote.status or quote.status.code not in review_states:
            return None, "INVALID_STATUS"
        if reason:
            note = f"Возврат на доработку: {reason}"
            quote.notes = f"{quote.notes}\n{note}".strip() if quote.notes else note
            quote.save(update_fields=["notes", "updated_at"])
        _set_quote_status(quote, QuoteStatusCode.DRAFT)
        _log_quote(quote, actor, "quote.send_back", f"КП v{quote.version} возвращено на доработку. {reason}".strip())
        return quote, None

    @staticmethod
    @transaction.atomic
    def force_approve_quote(
        quote_id: int,
        admin_user: CustomUser,
        reason: str = "",
    ) -> Tuple[Optional[Quote], Optional[str]]:
        """Platform-admin force override: approve a quote regardless of its current status.

        Used for escalations (e.g. client unreachable but verbally approved offline).
        Logged with [FORCE_ADMIN] marker so audit can distinguish from normal flow.
        Caller must have SystemRole.ADMIN or be is_superuser. Viewer-mode admins
        (ADMIN without a CompanyMember) are explicitly permitted — force-actions
        are platform-admin moderation, not bound to membership.
        """
        from django.utils import timezone

        if not (
            getattr(admin_user, "is_superuser", False)
            or (admin_user.role and admin_user.role.code == SystemRoleCode.ADMIN)
        ):
            return None, "PLATFORM_ADMIN_REQUIRED"
        if not reason.strip():
            return None, "FORCE_REASON_REQUIRED"
        # of=("self",): Quote.status is a nullable FK, so select_related("status")
        # emits a LEFT OUTER JOIN, and Postgres rejects "FOR UPDATE" on the nullable
        # side of an outer join. Lock only the crm_quote row, not the joined tables.
        quote = Quote.objects.select_for_update(of=("self",)).select_related("deal", "status").get(pk=quote_id)
        approved = QuoteStatus.objects.filter(code=QuoteStatusCode.APPROVED).first()
        if not approved:
            return None, "QUOTE_STATUS_NOT_FOUND"
        old_code = quote.status.code if quote.status else "None"
        quote.status = approved
        quote.approved_at = timezone.now()
        quote.approved_by = admin_user
        quote.notes = (
            f"{quote.notes}\n[FORCE_ADMIN] {admin_user.email}: {reason}"
            if quote.notes
            else f"[FORCE_ADMIN] {admin_user.email}: {reason}"
        )
        quote.save(update_fields=["status", "approved_at", "approved_by", "notes", "updated_at"])
        ActivityLog.objects.create(
            action="[FORCE_ADMIN] КП одобрено платформенным админом",
            detail=f"КП #{quote_id} ({old_code} → APPROVED). Причина: {reason}",
            user=admin_user,
            level="WARNING",
        )
        return quote, None

    @staticmethod
    @transaction.atomic
    def reject_quote(quote_id: int, rejected_by_user, reason: str = "") -> Quote:
        """Client rejects the quote. Only SENT quotes can be rejected."""

        quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else "None"
        if current != QuoteStatusCode.SENT:
            raise ValueError(f"Cannot reject quote in status '{current}'. " "Only SENT quotes can be rejected.")

        rejected_status = QuoteStatus.objects.filter(code=QuoteStatusCode.REJECTED).first()
        quote.status = rejected_status
        # Append rejection reason instead of replacing notes
        if reason:
            rejection_note = f"Причина отказа: {reason}"
            quote.notes = f"{quote.notes}\n{rejection_note}".strip() if quote.notes else rejection_note
        quote.save(update_fields=["status", "notes", "updated_at"])

        # Move deal back to CALCULATING via FSM
        transition_deal_stage(
            quote.deal,
            DealStageCode.CALCULATING,
            actor=rejected_by_user,
            reason=f"КП v{quote.version} отклонено. {reason}",
        )

        # Notify the КП author (+ distinct manager) that the client rejected —
        # same single-seller reasoning as approve_quote. Pushed over WS.
        _notify_quote_outcome(
            quote,
            type_code="WARNING",
            title="КП отклонено клиентом",
            message=f"{quote.deal.company.name} отклонил КП v{quote.version}. {reason}".strip(),
        )

        return quote


# ──────────────────────────────────────────────────────────────────────────
# Re-match (manual reassign QuoteItem.product)
# ──────────────────────────────────────────────────────────────────────────


@transaction.atomic
def reassign_quote_item_product(
    quote_item_id: int,
    actor: CustomUser,
    product_id: Optional[int],
) -> Tuple[Optional[QuoteItem], Optional[str]]:
    """Allow manager to override Smart Match result by picking a different product."""
    from accounts.services import is_platform_admin_viewer
    from catalog.models import Product

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    item = QuoteItem.objects.select_for_update().select_related("quote").get(pk=quote_item_id)
    if item.quote.frozen_at:
        return None, "QUOTE_FROZEN_CANNOT_REASSIGN"
    if product_id:
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            return None, "PRODUCT_NOT_FOUND"
        item.product = product
    else:
        item.product = None
    item.save(update_fields=["product", "assigned_at"])
    ActivityLog.objects.create(
        action="Переназначен продукт в позиции КП",
        detail=f"QuoteItem #{item.id} → Product #{product_id}",
        user=actor,
        level="INFO",
    )
    return item, None


# ── Buyer-editable request (заявка) line items ──────────────────────────────
# The buyer owns the *request*: the list of what they want to procure. Those
# rows live on the deal's single DRAFT quote (created here on first add, or by
# the Excel importer). Editing is name + quantity ONLY — never pricing, which is
# the seller's job — and only BEFORE the seller takes the deal into work. Once
# the seller starts pricing (stage leaves the pre-work set) the request freezes.
# Editable only while the buyer is still drafting — before they submit the RFQ.
# Submitting moves DRAFT → RFQ_OPEN (see submit_request), which locks the request.
REQUEST_EDITABLE_STAGES = frozenset({DealStageCode.DRAFT})


def buyer_can_edit_request(deal: Deal, user: CustomUser) -> bool:
    """True if `user` may add/edit/remove the request line items on `deal`."""
    from accounts.services.permissions import is_member_of, is_platform_admin_viewer

    if is_platform_admin_viewer(user):
        return False
    if not is_member_of(user, deal.company_id, capability="buy"):
        return False
    stage_code = deal.stage.code if deal.stage_id else None
    return stage_code in REQUEST_EDITABLE_STAGES


def _request_draft_quote(deal: Deal) -> Quote:
    """The single DRAFT quote holding the buyer's requested items (get-or-create)."""
    quote = deal.quotes.filter(status__code=QuoteStatusCode.DRAFT).order_by("version").first()
    if quote:
        return quote
    draft_status = QuoteStatus.objects.get(code=QuoteStatusCode.DRAFT)
    next_version = (deal.quotes.aggregate(m=models.Max("version"))["m"] or 0) + 1
    return Quote.objects.create(deal=deal, version=next_version, status=draft_status)


def _assert_request_editable(deal: Deal, user: CustomUser) -> None:
    from rest_framework.exceptions import PermissionDenied

    if not buyer_can_edit_request(deal, user):
        raise PermissionDenied("REQUEST_NOT_EDITABLE")


def _line_dedup_key(item: QuoteItem):
    """Identity of a request line for dedup: prefer code (mpn / ГОСТ-чертёж), else name+unit."""
    mpn = (item.mpn or "").strip().lower()
    if mpn:
        return ("mpn", mpn)
    gost = (item.gost_drawing or "").strip().lower()
    if gost:
        return ("gost", gost)
    name = (item.imported_raw_name or (item.product.name if item.product_id and item.product else "")).strip().lower()
    return ("name", name, (item.unit or "").strip().lower())


def merge_request_lines(quote: Quote, new_items: list) -> tuple:
    """Add unsaved QuoteItem rows to `quote`, deduping by mpn / ГОСТ / (name+unit)
    against existing lines AND within the batch — same item ⇒ quantities sum.
    Idempotent for re-imports. Returns (created_list, merged_count)."""
    existing = {}
    for line in quote.items.all():
        existing[_line_dedup_key(line)] = line
    created, touched, merged = [], [], 0
    for incoming in new_items:
        key = _line_dedup_key(incoming)
        if key in existing:
            existing[key].quantity += incoming.quantity
            if existing[key].pk:
                touched.append(existing[key])
            merged += 1
        else:
            existing[key] = incoming
            created.append(incoming)
    if created:
        QuoteItem.objects.bulk_create(created)
    for line in touched:
        line.save(update_fields=["quantity"])
    return created, merged


@transaction.atomic
def buyer_add_request_item(
    user: CustomUser, deal: Deal, *, name: str, quantity, unit="", unit_code="", note="", mpn=""
) -> QuoteItem:
    from rest_framework.exceptions import ValidationError

    clean_name = (name or "").strip()
    if not clean_name:
        raise ValidationError({"name": "ITEM_NAME_REQUIRED"})
    _assert_request_editable(deal, user)
    quote = _request_draft_quote(deal)
    # Lock the draft quote so concurrent adds of the same line serialize — the
    # dedup read-modify-write on `quantity` below would otherwise lose an update.
    quote = Quote.objects.select_for_update().get(pk=quote.pk)
    candidate = QuoteItem(
        quote=quote,
        imported_raw_name=clean_name,
        quantity=max(1, int(quantity or 1)),
        unit=(unit or "")[:32],
        unit_code=(unit_code or "")[:8],
        note=note or "",
        # Article (MPN) parity with the edit path — without it a new line drops the
        # article. Set before _line_dedup_key, which prefers mpn for dedup.
        mpn=(mpn or "")[:120],
    )
    # Same dedup as cart/import: re-adding an identical line sums the quantity.
    key = _line_dedup_key(candidate)
    existing = next((line for line in quote.items.all() if _line_dedup_key(line) == key), None)
    if existing:
        existing.quantity += candidate.quantity
        existing.save(update_fields=["quantity"])
        item = existing
    else:
        candidate.save()
        item = candidate
    quote.recalculate_totals()
    ActivityLog.objects.create(
        action="Добавлена позиция заявки",
        detail=f"Deal #{deal.id}: «{clean_name}» × {item.quantity}",
        user=user,
        level="INFO",
        entity_type="deal",
        entity_id=str(deal.id),
    )
    return item


@transaction.atomic
def buyer_add_request_items(user: CustomUser, deal: Deal, rows: list) -> list:
    """Bulk-add request lines — used by the catalog cart checkout. Each row is
    {product_id?, name?, quantity, unit?}. Catalog items link to the real Product
    (so the seller gets a pre-matched line), free rows fall back to imported_raw_name.
    """
    from django.utils import timezone

    from catalog.models import Product

    _assert_request_editable(deal, user)
    quote = _request_draft_quote(deal)
    # Lock the draft quote so a concurrent cart checkout / single-add doesn't
    # race the merge_request_lines read-modify-write (lost quantity update).
    quote = Quote.objects.select_for_update().get(pk=quote.pk)
    to_create = []
    for row in rows or []:
        product = None
        product_id = row.get("product_id")
        if product_id:
            product = Product.objects.filter(pk=product_id).first()
        name = (row.get("name") or (product.name if product else "")).strip()
        if not (name or product):
            continue
        to_create.append(
            QuoteItem(
                quote=quote,
                product=product,
                imported_raw_name="" if product else name,
                quantity=max(1, int(row.get("quantity") or 1)),
                unit=(row.get("unit") or "")[:32],
                unit_code=(row.get("unit_code") or "")[:8],
                note=row.get("note") or "",
                assigned_at=timezone.now() if product else None,
            )
        )
    if to_create:
        merge_request_lines(quote, to_create)
        quote.recalculate_totals()
        ActivityLog.objects.create(
            action="Добавлены позиции заявки (корзина)",
            detail=f"Deal #{deal.id}: {len(to_create)} позиций",
            user=user,
            level="INFO",
            entity_type="deal",
            entity_id=str(deal.id),
        )
    return to_create


def buyer_update_request_item(user: CustomUser, item: QuoteItem, *, name=None, quantity=None, unit=None, unit_code=None, note=None, mpn=None) -> QuoteItem:
    from rest_framework.exceptions import ValidationError

    deal = item.quote.deal
    _assert_request_editable(deal, user)
    fields = []
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValidationError({"name": "ITEM_NAME_REQUIRED"})
        item.imported_raw_name = clean_name
        fields.append("imported_raw_name")
    if quantity is not None:
        item.quantity = max(1, int(quantity))
        fields.append("quantity")
    if unit is not None:
        item.unit = (unit or "")[:32]
        fields.append("unit")
    if unit_code is not None:
        item.unit_code = (unit_code or "")[:8]
        fields.append("unit_code")
    if note is not None:
        item.note = note or ""
        fields.append("note")
    if mpn is not None:
        item.mpn = (mpn or "")[:120]
        fields.append("mpn")
    if fields:
        item.save(update_fields=fields)
        item.quote.recalculate_totals()
    return item


def buyer_remove_request_item(user: CustomUser, item: QuoteItem) -> None:
    deal = item.quote.deal
    _assert_request_editable(deal, user)
    quote = item.quote
    item.delete()
    quote.recalculate_totals()
    ActivityLog.objects.create(
        action="Удалена позиция заявки",
        detail=f"Deal #{deal.id}: QuoteItem #{item.id}",
        user=user,
        level="INFO",
        entity_type="deal",
        entity_id=str(deal.id),
    )


def _is_request_item_incomplete(item: QuoteItem) -> bool:
    # UBL: a line must be identified by a name OR a code (mpn / ГОСТ-чертёж) OR a product.
    return not (
        (item.imported_raw_name or "").strip()
        or (item.mpn or "").strip()
        or (item.gost_drawing or "").strip()
        or item.product_id
    )


def buyer_update_request_meta(user: CustomUser, deal: Deal, *, title=None, notes=None) -> Deal:
    """Buyer edits the request header — title + note-to-seller — while still DRAFT."""
    from rest_framework.exceptions import PermissionDenied, ValidationError

    if not buyer_can_edit_request(deal, user):
        raise PermissionDenied("REQUEST_NOT_EDITABLE")
    fields = []
    if title is not None:
        clean = title.strip()
        if not clean:
            raise ValidationError({"title": "TITLE_REQUIRED"})
        deal.title = clean[:255]
        fields.append("title")
    if notes is not None:
        deal.notes = notes
        fields.append("notes")
    if fields:
        deal.save(update_fields=fields)
    return deal


def submit_request(user: CustomUser, deal: Deal) -> Deal:
    """Buyer issues the RFQ to the seller — the explicit «Отправить заявку» step.

    World-standard RFQ lifecycle: Draft → SUBMIT → seller quotes → accept/reject.
    Guards: buyer with can_buy, deal still DRAFT, ≥1 line, and NO incomplete lines
    (the data-quality gate). On success the deal moves DRAFT → RFQ_OPEN via the FSM
    and the buyer's request locks for editing.
    """
    from rest_framework.exceptions import PermissionDenied, ValidationError

    from accounts.services.permissions import is_member_of, is_platform_admin_viewer

    if is_platform_admin_viewer(user):
        raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
    if not is_member_of(user, deal.company_id, capability="buy"):
        raise PermissionDenied("ONLY_BUYER_CAN_SUBMIT_REQUEST")
    if (deal.stage.code if deal.stage_id else None) != DealStageCode.DRAFT:
        raise ValidationError({"detail": "REQUEST_ALREADY_SUBMITTED"})

    quote = deal.quotes.filter(status__code=QuoteStatusCode.DRAFT).order_by("version").first()
    items = list(quote.items.all()) if quote else []
    if not items:
        raise ValidationError({"detail": "REQUEST_EMPTY"})
    if any(_is_request_item_incomplete(item) for item in items):
        raise ValidationError({"detail": "REQUEST_HAS_INCOMPLETE_ITEMS"})

    deal, error = transition_deal_stage(deal, DealStageCode.RFQ_OPEN, actor=user)
    if error:
        raise ValidationError({"detail": error})
    ActivityLog.objects.create(
        action="Заявка отправлена поставщику (RFQ)",
        detail=f"Deal #{deal.id}: {len(items)} позиций",
        user=user,
        level="INFO",
        entity_type="deal",
        entity_id=str(deal.id),
    )
    return deal
