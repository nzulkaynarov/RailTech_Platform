from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Tuple

from django.db import models, transaction
from django.db.models import Count, Q, Sum

from accounts.models import Company, CompanyMember, CustomUser
from accounts.services.permissions import has_workspace_role

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
    "SALES_MANAGER": {"DRAFT"},
    "FOREIGN_TRADE_SPECIALIST": {"PENDING_TRADE_REVIEW"},
    "DIRECTOR": {"PENDING_APPROVAL"},
    "OWNER": {"DRAFT", "PENDING_TRADE_REVIEW", "PENDING_APPROVAL", "READY_TO_SEND"},
}


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

    kyc_backlog = Company.objects.filter(verification_status__code__in=["L1_UNVERIFIED", "PROFILE_SUBMITTED"]).count()

    total_pipeline_value = (
        Quote.objects.filter(status__code__in=["SENT", "APPROVED"]).aggregate(total=Sum("total_incl_vat"))["total"] or 0
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
        if current != "READY_TO_SEND":
            raise ValueError(
                f"Cannot send quote in status '{current}'. "
                "Only READY_TO_SEND quotes (internally approved) can be sent to the client."
            )

        # Generate PDF if missing
        if not quote.pdf_file:
            quote = QuoteLifecycleService.generate_pdf(quote_id)
            quote.refresh_from_db()

        # Freeze prices
        sent_status = QuoteStatus.objects.filter(code="SENT").first()
        quote.status = sent_status
        quote.frozen_at = timezone.now()
        quote.save(update_fields=["status", "frozen_at", "updated_at"])

        # Change deal stage via FSM
        transition_deal_stage(
            quote.deal,
            "QUOTE_SENT",
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

        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else "None"
        if current != "SENT":
            raise ValueError(f"Cannot approve quote in status '{current}'. " "Only SENT quotes can be approved.")

        approved_status = QuoteStatus.objects.filter(code="APPROVED").first()
        quote.status = approved_status
        quote.approved_at = timezone.now()
        quote.approved_by = approved_by_user
        quote.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])

        # Change deal stage via FSM
        transition_deal_stage(
            quote.deal,
            "CONTRACT_SIGNED",
            actor=approved_by_user,
            reason=f"КП v{quote.version} одобрено клиентом",
        )

        # Notify manager
        if quote.deal.manager:
            success_type = NotificationType.objects.filter(code="SUCCESS").first()
            Notification.objects.create(
                user=quote.deal.manager,
                type=success_type,
                title="КП одобрено клиентом",
                message=f"{quote.deal.company.name} одобрил КП v{quote.version}",
                link="/crm/deals",
                deal=quote.deal,
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
        if not has_workspace_role(actor, company_id, ["SALES_MANAGER"]):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != "DRAFT":
            return None, "INVALID_STATUS"
        has_trade = CompanyMember.objects.filter(
            company_id=company_id, is_active=True, role__code="FOREIGN_TRADE_SPECIALIST"
        ).exists()
        next_code = "PENDING_TRADE_REVIEW" if has_trade else "PENDING_APPROVAL"
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
        if not has_workspace_role(actor, company_id, ["FOREIGN_TRADE_SPECIALIST"]):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != "PENDING_TRADE_REVIEW":
            return None, "INVALID_STATUS"
        _set_quote_status(quote, "PENDING_APPROVAL")
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
        if not has_workspace_role(actor, company_id, ["DIRECTOR"]):
            return None, "ROLE_NOT_PERMITTED"
        if not quote.status or quote.status.code != "PENDING_APPROVAL":
            return None, "INVALID_STATUS"
        _set_quote_status(quote, "READY_TO_SEND")
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
        if not has_workspace_role(actor, company_id, ["FOREIGN_TRADE_SPECIALIST", "DIRECTOR"]):
            return None, "ROLE_NOT_PERMITTED"
        review_states = {"PENDING_TRADE_REVIEW", "PENDING_APPROVAL", "READY_TO_SEND"}
        if not quote.status or quote.status.code not in review_states:
            return None, "INVALID_STATUS"
        if reason:
            note = f"Возврат на доработку: {reason}"
            quote.notes = f"{quote.notes}\n{note}".strip() if quote.notes else note
            quote.save(update_fields=["notes", "updated_at"])
        _set_quote_status(quote, "DRAFT")
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

        if not (getattr(admin_user, "is_superuser", False) or (admin_user.role and admin_user.role.code == "ADMIN")):
            return None, "PLATFORM_ADMIN_REQUIRED"
        if not reason.strip():
            return None, "FORCE_REASON_REQUIRED"
        # of=("self",): Quote.status is a nullable FK, so select_related("status")
        # emits a LEFT OUTER JOIN, and Postgres rejects "FOR UPDATE" on the nullable
        # side of an outer join. Lock only the crm_quote row, not the joined tables.
        quote = Quote.objects.select_for_update(of=("self",)).select_related("deal", "status").get(pk=quote_id)
        approved = QuoteStatus.objects.filter(code="APPROVED").first()
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
        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related("deal__company", "deal__manager", "deal__stage", "status").get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else "None"
        if current != "SENT":
            raise ValueError(f"Cannot reject quote in status '{current}'. " "Only SENT quotes can be rejected.")

        rejected_status = QuoteStatus.objects.filter(code="REJECTED").first()
        quote.status = rejected_status
        # Append rejection reason instead of replacing notes
        if reason:
            rejection_note = f"Причина отказа: {reason}"
            quote.notes = f"{quote.notes}\n{rejection_note}".strip() if quote.notes else rejection_note
        quote.save(update_fields=["status", "notes", "updated_at"])

        # Move deal back to CALCULATING via FSM
        transition_deal_stage(
            quote.deal,
            "CALCULATING",
            actor=rejected_by_user,
            reason=f"КП v{quote.version} отклонено. {reason}",
        )

        # Notify manager
        if quote.deal.manager:
            warning_type = NotificationType.objects.filter(code="WARNING").first()
            Notification.objects.create(
                user=quote.deal.manager,
                type=warning_type,
                title="КП отклонено клиентом",
                message=f"{quote.deal.company.name} отклонил КП v{quote.version}. {reason}",
                link="/crm/deals",
                deal=quote.deal,
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
