from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Tuple

from django.db import models, transaction
from django.db.models import Count, Sum

from accounts.models import Company, CustomUser

from ..models import ActivityLog, Deal, Quote, QuoteItem, QuoteItemHistory, QuoteStatus
from .deals import transition_deal_stage


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
        1. Guard: only DRAFT quotes can be sent
        2. Generate PDF if not exists
        3. Set frozen_at timestamp
        4. Change status to SENT
        5. Change deal stage to QUOTE_SENT via FSM
        6. Create notification for client
        """
        from django.utils import timezone

        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related("deal__company", "deal__client", "deal__stage", "status").get(pk=quote_id)

        # Status guard: only DRAFT can be sent
        if quote.status and quote.status.code != "DRAFT":
            raise ValueError(f"Cannot send quote in status '{quote.status.code}'. " "Only DRAFT quotes can be sent.")

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
        quote = Quote.objects.select_for_update().select_related("deal", "status").get(pk=quote_id)
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
