from decimal import Decimal
from typing import Optional, Tuple

from django.db import transaction, models
from django.db.models import Count, QuerySet, Sum

from accounts.models import Company, CustomUser

from .models import ActivityLog, Deal, DealStage, Lead, Quote, QuoteItem, QuoteStatus


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
        is_service = (
            item.product
            and item.product.domain_type
            and item.product.domain_type.code == 'SERVICES'
        )

        if is_service:
            item.landed_cost = item.frozen_base_price
            item.logistics_cost = Decimal('0')
            item.customs_duty = Decimal('0')
        else:
            item.landed_cost = (
                item.frozen_base_price +
                item.logistics_cost +
                item.customs_duty
            )

        margin_mult = Decimal('1') + (item.margin_percent / Decimal('100'))
        item.final_price_excl_vat = item.landed_cost * margin_mult

        if commit:
            item.save(update_fields=['landed_cost', 'final_price_excl_vat', 'logistics_cost', 'customs_duty'])

        return item

    @classmethod
    @transaction.atomic
    def recalculate_quote(cls, quote_id: int):
        """
        Full recalculation of a Quote and all its items.
        Prevents N+1 updates by using aggregation.
        """
        quote = Quote.objects.select_for_update().get(pk=quote_id)
        items = list(quote.items.select_related('product__domain_type').all())

        # 1. Recalculate each item price (without saving each time to DB yet)
        for item in items:
            cls.calculate_item_prices(item, commit=False)

        # 2. Bulk update items to minimize DB hits
        QuoteItem.objects.bulk_update(
            items,
            ['landed_cost', 'final_price_excl_vat', 'logistics_cost', 'customs_duty']
        )

        # 3. Aggregation for Quote totals (use QuerySet, not list)
        totals = quote.items.aggregate(
            subtotal=models.Sum(models.F('final_price_excl_vat') * models.F('quantity'))
        )

        subtotal = totals['subtotal'] or Decimal('0')
        vat_rate = quote.vat_rate / Decimal('100')

        quote.subtotal_excl_vat = subtotal
        quote.vat_amount = subtotal * vat_rate
        quote.total_incl_vat = subtotal + quote.vat_amount

        quote.save(update_fields=['subtotal_excl_vat', 'vat_amount', 'total_incl_vat', 'updated_at'])
        return quote


def get_crm_analytics_data():
    """LOW-4: Extracted analytics logic from views to service."""
    deals = Deal.objects.all()
    items = QuoteItem.objects.all()

    pipeline_by_status = list(deals.values('stage__name').annotate(count=Count('id')))
    sourcing_backlog = items.filter(product__isnull=True).count()

    total_items = items.count()
    mapped_items = items.filter(product__isnull=False).count()
    mapped_items_percentage = (mapped_items / total_items * 100) if total_items > 0 else 0

    kyc_backlog = Company.objects.filter(
        verification_status__code__in=['L1_UNVERIFIED', 'PROFILE_SUBMITTED']
    ).count()

    total_pipeline_value = Quote.objects.filter(
        status__code__in=['SENT', 'APPROVED']
    ).aggregate(total=Sum('total_incl_vat'))['total'] or 0

    return {
        "pipeline_by_status": pipeline_by_status,
        "sourcing_backlog": sourcing_backlog,
        "kyc_backlog": kyc_backlog,
        "total_pipeline_value": float(total_pipeline_value),
        "mapped_items_percentage": round(mapped_items_percentage, 1)
    }


class QuoteLifecycleService:
    """Manages Quote state transitions: generate PDF, send, approve, reject."""

    @staticmethod
    @transaction.atomic
    def generate_pdf(quote_id: int) -> Quote:
        """Generate PDF for a quote using WeasyPrint."""
        from django.template.loader import render_to_string
        from weasyprint import HTML
        from io import BytesIO
        from django.core.files.base import ContentFile

        quote = Quote.objects.select_related(
            'deal__company', 'status', 'tax_country', 'prepared_by'
        ).prefetch_related('items__product__domain_type').get(pk=quote_id)

        html_string = render_to_string('crm/quote_pdf.html', {
            'quote': quote,
            'items': quote.items.select_related('product', 'frozen_currency').all(),
            'company': quote.deal.company,
        })

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
        1. Generate PDF if not exists
        2. Set frozen_at timestamp
        3. Change status to SENT
        4. Change deal stage to QUOTE_SENT
        5. Create notification for client
        """
        from django.utils import timezone
        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related('deal__company', 'deal__client', 'deal__stage').get(pk=quote_id)

        # Generate PDF if missing
        if not quote.pdf_file:
            quote = QuoteLifecycleService.generate_pdf(quote_id)
            quote.refresh_from_db()

        # Freeze prices
        sent_status = QuoteStatus.objects.filter(code='SENT').first()
        quote.status = sent_status
        quote.frozen_at = timezone.now()
        quote.save(update_fields=['status', 'frozen_at', 'updated_at'])

        # Change deal stage to QUOTE_SENT
        quote_sent_stage = DealStage.objects.filter(code='QUOTE_SENT').first()
        if quote_sent_stage:
            quote.deal.stage = quote_sent_stage
            quote.deal.save(update_fields=['stage'])

        # Create notification for client contact
        if quote.deal.client:
            info_type = NotificationType.objects.filter(code='INFO').first()
            Notification.objects.create(
                user=quote.deal.client,
                type=info_type,
                title="Новое коммерческое предложение",
                message=f"Вам отправлено КП v{quote.version} по сделке #{quote.deal_id}",
                link="/cabinet/deals",
                deal=quote.deal,
            )

        # Activity log
        ActivityLog.objects.create(
            action="КП отправлено клиенту",
            detail=f"КП v{quote.version} для {quote.deal.company.name} отправлено",
            user=sent_by_user,
            level='SUCCESS'
        )

        return quote

    @staticmethod
    @transaction.atomic
    def approve_quote(quote_id: int, approved_by_user) -> Quote:
        """Client approves the quote."""
        from django.utils import timezone
        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related('deal__company', 'deal__manager').get(pk=quote_id)

        approved_status = QuoteStatus.objects.filter(code='APPROVED').first()
        quote.status = approved_status
        quote.approved_at = timezone.now()
        quote.approved_by = approved_by_user
        quote.save(update_fields=['status', 'approved_at', 'approved_by', 'updated_at'])

        # Change deal stage to CONTRACT_SIGNED
        contract_stage = DealStage.objects.filter(code='CONTRACT_SIGNED').first()
        if contract_stage:
            quote.deal.stage = contract_stage
            quote.deal.save(update_fields=['stage'])

        # Notify manager
        if quote.deal.manager:
            success_type = NotificationType.objects.filter(code='SUCCESS').first()
            Notification.objects.create(
                user=quote.deal.manager,
                type=success_type,
                title="КП одобрено клиентом",
                message=f"{quote.deal.company.name} одобрил КП v{quote.version}",
                link="/crm/deals",
                deal=quote.deal,
            )

        ActivityLog.objects.create(
            action="КП одобрено",
            detail=f"КП v{quote.version} одобрено {approved_by_user.email}",
            user=approved_by_user,
            level='SUCCESS'
        )

        return quote

    @staticmethod
    @transaction.atomic
    def reject_quote(quote_id: int, rejected_by_user, reason: str = '') -> Quote:
        """Client rejects the quote."""
        from django.utils import timezone
        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related('deal__company', 'deal__manager').get(pk=quote_id)

        rejected_status = QuoteStatus.objects.filter(code='REJECTED').first()
        quote.status = rejected_status
        quote.notes = f"Причина отказа: {reason}" if reason else quote.notes
        quote.save(update_fields=['status', 'notes', 'updated_at'])

        # Move deal back to CALCULATING for revision
        calc_stage = DealStage.objects.filter(code='CALCULATING').first()
        if calc_stage:
            quote.deal.stage = calc_stage
            quote.deal.save(update_fields=['stage'])

        # Notify manager
        if quote.deal.manager:
            warning_type = NotificationType.objects.filter(code='WARNING').first()
            Notification.objects.create(
                user=quote.deal.manager,
                type=warning_type,
                title="КП отклонено клиентом",
                message=f"{quote.deal.company.name} отклонил КП v{quote.version}. {reason}",
                link="/crm/deals",
                deal=quote.deal,
            )

        ActivityLog.objects.create(
            action="КП отклонено",
            detail=f"КП v{quote.version} отклонено. {reason}",
            user=rejected_by_user,
            level='WARNING'
        )

        return quote


# ──────────────────────────────────────────────────────────────────────────
# Admin operations — single source of truth for business logic.
# Called from both Django Unfold actions and DRF endpoints.
# See ADR-0001 and CLAUDE.md IRON RULE 8.
# ──────────────────────────────────────────────────────────────────────────


ALLOWED_STAGE_TRANSITIONS = {
    'DRAFT': ['KYC_PENDING', 'SOURCING', 'CLOSED_LOST'],
    'KYC_PENDING': ['SOURCING', 'CLOSED_LOST'],
    'SOURCING': ['CALCULATING', 'CLOSED_LOST'],
    'CALCULATING': ['QUOTE_SENT', 'SOURCING', 'CLOSED_LOST'],
    'QUOTE_SENT': ['CONTRACT_SIGNED', 'CALCULATING', 'CLOSED_LOST'],
    'CONTRACT_SIGNED': ['CLOSED_WON', 'CLOSED_LOST'],
    'CLOSED_WON': [],
    'CLOSED_LOST': [],
}


def get_allowed_transitions(stage_code: str) -> list[str]:
    """Return list of stage codes reachable from the given stage."""
    return ALLOWED_STAGE_TRANSITIONS.get(stage_code, [])


def transition_deal_stage(
    deal: Deal,
    target_stage_code: str,
    actor: Optional[CustomUser] = None,
    reason: str = '',
    validate_fsm: bool = True,
) -> Tuple[Optional[Deal], Optional[str]]:
    """
    Transition a Deal to a new stage by stage code.

    When validate_fsm=True, enforces the FSM transition matrix.
    Logs the change to ActivityLog.
    Returns: (deal, error_or_None)
    """
    target_stage = DealStage.objects.filter(code=target_stage_code).first()
    if not target_stage:
        return None, f"DealStage '{target_stage_code}' not found"

    if deal.stage and deal.stage.code == target_stage_code:
        return deal, None  # already in target state, no-op

    if validate_fsm:
        current_code = deal.stage.code if deal.stage else 'DRAFT'
        allowed = get_allowed_transitions(current_code)
        if target_stage_code not in allowed:
            allowed_str = ', '.join(allowed) if allowed else 'none (terminal state)'
            return None, f"Transition {current_code} → {target_stage_code} is not allowed. Allowed: {allowed_str}"

    old_stage_name = deal.stage.name if deal.stage else '—'
    deal.stage = target_stage
    deal.save(update_fields=['stage'])

    ActivityLog.objects.create(
        action="Стадия изменена",
        detail=f"Сделка #{deal.id}: {old_stage_name} → {target_stage.name}{' · ' + reason if reason else ''}",
        user=actor,
        level='INFO',
    )
    return deal, None


def bulk_close_deals_lost(
    deals: QuerySet[Deal],
    actor: Optional[CustomUser] = None,
) -> int:
    """
    Mark deals as CLOSED_LOST. Skips deals already in any closed state.

    Returns: count of deals updated.
    """
    closed_lost = DealStage.objects.filter(code='CLOSED_LOST').first()
    if not closed_lost:
        return 0
    open_deals = deals.exclude(stage__code__in=['CLOSED_WON', 'CLOSED_LOST'])
    count = 0
    for deal in open_deals:
        _, error = transition_deal_stage(deal, 'CLOSED_LOST', actor=actor)
        if not error:
            count += 1
    return count


def mark_leads_processed(leads: QuerySet[Lead]) -> int:
    """
    Mark a queryset of leads as processed.

    Returns: count of leads updated (only previously-unprocessed ones).
    """
    return leads.filter(is_processed=False).update(is_processed=True)
