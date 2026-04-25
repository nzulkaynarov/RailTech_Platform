import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple

from django.db import transaction, models
from django.db.models import Count, QuerySet, Sum

from accounts.models import Company, CustomUser

from .models import ActivityLog, Deal, DealStage, Lead, Message, Quote, QuoteItem, QuoteItemHistory, QuoteStatus


# ──────────────────────────────────────────────────────────────────────────
# Parameter dataclasses — reduce long argument lists (Sprint 4b).
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class PaymentData:
    """Groups payment-related parameters for record_payment()."""
    invoice_id: int
    amount: object  # Decimal-coercible (str, int, float, Decimal)
    paid_at: object  # date or datetime
    method: str = 'BANK_TRANSFER'
    reference: str = ''
    proof_file: Optional[object] = None
    manual: bool = True


@dataclass
class BidSubmission:
    """Groups supplier bid parameters for submit_supplier_bid()."""
    deal_id: int
    supplier_id: int
    items: list = field(default_factory=list)
    notes: str = ''
    lead_time_days: Optional[int] = None
    currency_id: Optional[int] = None

logger = logging.getLogger(__name__)


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
        item.final_price_excl_vat = (
            item.landed_cost * margin_mult
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

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
                change_reason='recalculation',
            )
            for item in items
        ]
        if history_records:
            QuoteItemHistory.objects.bulk_create(history_records)

        # 3. Aggregation for Quote totals (use QuerySet, not list)
        totals = quote.items.aggregate(
            subtotal=models.Sum(models.F('final_price_excl_vat') * models.F('quantity'))
        )

        subtotal = totals['subtotal'] or Decimal('0')
        vat_rate = quote.vat_rate / Decimal('100')

        penny = Decimal('0.01')
        quote.subtotal_excl_vat = subtotal.quantize(penny, rounding=ROUND_HALF_UP)
        quote.vat_amount = (subtotal * vat_rate).quantize(penny, rounding=ROUND_HALF_UP)
        quote.total_incl_vat = (quote.subtotal_excl_vat + quote.vat_amount)

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
        1. Guard: only DRAFT quotes can be sent
        2. Generate PDF if not exists
        3. Set frozen_at timestamp
        4. Change status to SENT
        5. Change deal stage to QUOTE_SENT via FSM
        6. Create notification for client
        """
        from django.utils import timezone
        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related(
            'deal__company', 'deal__client', 'deal__stage', 'status'
        ).get(pk=quote_id)

        # Status guard: only DRAFT can be sent
        if quote.status and quote.status.code != 'DRAFT':
            raise ValueError(
                f"Cannot send quote in status '{quote.status.code}'. "
                "Only DRAFT quotes can be sent."
            )

        # Generate PDF if missing
        if not quote.pdf_file:
            quote = QuoteLifecycleService.generate_pdf(quote_id)
            quote.refresh_from_db()

        # Freeze prices
        sent_status = QuoteStatus.objects.filter(code='SENT').first()
        quote.status = sent_status
        quote.frozen_at = timezone.now()
        quote.save(update_fields=['status', 'frozen_at', 'updated_at'])

        # Change deal stage via FSM
        transition_deal_stage(
            quote.deal, 'QUOTE_SENT', actor=sent_by_user,
            reason=f"КП v{quote.version} отправлено клиенту",
        )

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

        return quote

    @staticmethod
    @transaction.atomic
    def approve_quote(quote_id: int, approved_by_user) -> Quote:
        """Client approves the quote. Only SENT quotes can be approved."""
        from django.utils import timezone
        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related(
            'deal__company', 'deal__manager', 'deal__stage', 'status'
        ).get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else 'None'
        if current != 'SENT':
            raise ValueError(
                f"Cannot approve quote in status '{current}'. "
                "Only SENT quotes can be approved."
            )

        approved_status = QuoteStatus.objects.filter(code='APPROVED').first()
        quote.status = approved_status
        quote.approved_at = timezone.now()
        quote.approved_by = approved_by_user
        quote.save(update_fields=['status', 'approved_at', 'approved_by', 'updated_at'])

        # Change deal stage via FSM
        transition_deal_stage(
            quote.deal, 'CONTRACT_SIGNED', actor=approved_by_user,
            reason=f"КП v{quote.version} одобрено клиентом",
        )

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

        return quote

    @staticmethod
    @transaction.atomic
    def force_approve_quote(
        quote_id: int, admin_user: CustomUser, reason: str = '',
    ) -> Tuple[Optional[Quote], Optional[str]]:
        """Platform-admin force override: approve a quote regardless of its current status.

        Used for escalations (e.g. client unreachable but verbally approved offline).
        Logged with [FORCE_ADMIN] marker so audit can distinguish from normal flow.
        Caller must have SystemRole.ADMIN or be is_superuser. Viewer-mode admins
        (ADMIN without a CompanyMember) are explicitly permitted — force-actions
        are platform-admin moderation, not bound to membership.
        """
        from django.utils import timezone
        if not (getattr(admin_user, 'is_superuser', False)
                or (admin_user.role and admin_user.role.code == 'ADMIN')):
            return None, 'PLATFORM_ADMIN_REQUIRED'
        if not reason.strip():
            return None, 'FORCE_REASON_REQUIRED'
        quote = Quote.objects.select_for_update().select_related('deal', 'status').get(pk=quote_id)
        approved = QuoteStatus.objects.filter(code='APPROVED').first()
        if not approved:
            return None, 'QUOTE_STATUS_NOT_FOUND'
        old_code = quote.status.code if quote.status else 'None'
        quote.status = approved
        quote.approved_at = timezone.now()
        quote.approved_by = admin_user
        quote.notes = (
            f"{quote.notes}\n[FORCE_ADMIN] {admin_user.email}: {reason}"
            if quote.notes else f"[FORCE_ADMIN] {admin_user.email}: {reason}"
        )
        quote.save(update_fields=['status', 'approved_at', 'approved_by', 'notes', 'updated_at'])
        ActivityLog.objects.create(
            action="[FORCE_ADMIN] КП одобрено платформенным админом",
            detail=f"КП #{quote_id} ({old_code} → APPROVED). Причина: {reason}",
            user=admin_user, level='WARNING',
        )
        return quote, None

    @staticmethod
    @transaction.atomic
    def reject_quote(quote_id: int, rejected_by_user, reason: str = '') -> Quote:
        """Client rejects the quote. Only SENT quotes can be rejected."""
        from notifications.models import Notification, NotificationType

        quote = Quote.objects.select_related(
            'deal__company', 'deal__manager', 'deal__stage', 'status'
        ).get(pk=quote_id)

        # Status guard
        current = quote.status.code if quote.status else 'None'
        if current != 'SENT':
            raise ValueError(
                f"Cannot reject quote in status '{current}'. "
                "Only SENT quotes can be rejected."
            )

        rejected_status = QuoteStatus.objects.filter(code='REJECTED').first()
        quote.status = rejected_status
        # Append rejection reason instead of replacing notes
        if reason:
            rejection_note = f"Причина отказа: {reason}"
            quote.notes = f"{quote.notes}\n{rejection_note}".strip() if quote.notes else rejection_note
        quote.save(update_fields=['status', 'notes', 'updated_at'])

        # Move deal back to CALCULATING via FSM
        transition_deal_stage(
            quote.deal, 'CALCULATING', actor=rejected_by_user,
            reason=f"КП v{quote.version} отклонено. {reason}",
        )

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

        return quote


# ──────────────────────────────────────────────────────────────────────────
# Admin operations — single source of truth for business logic.
# Called from both Django Unfold actions and DRF endpoints.
# See ADR-0001 and CLAUDE.md IRON RULE 8.
# ──────────────────────────────────────────────────────────────────────────


ALLOWED_STAGE_TRANSITIONS = {
    'DRAFT': ['KYC_PENDING', 'RFQ_OPEN', 'SOURCING', 'CLOSED_LOST'],
    'KYC_PENDING': ['RFQ_OPEN', 'SOURCING', 'CLOSED_LOST'],
    'RFQ_OPEN': ['SOURCING', 'CALCULATING', 'CLOSED_LOST'],
    'SOURCING': ['CALCULATING', 'CLOSED_LOST'],
    'CALCULATING': ['QUOTE_SENT', 'SOURCING', 'CLOSED_LOST'],
    'QUOTE_SENT': ['CONTRACT_SIGNED', 'CALCULATING', 'CLOSED_LOST'],
    'CONTRACT_SIGNED': ['CLOSED_WON', 'CLOSED_LOST'],
    # Terminal states are reopenable by manager for rare legitimate cases.
    'CLOSED_WON': ['CONTRACT_SIGNED'],
    'CLOSED_LOST': ['CALCULATING', 'SOURCING'],
}


# Stage codes that require a signed Contract before entering.
STAGE_REQUIRES_SIGNED_CONTRACT = {'CLOSED_WON'}


def get_allowed_transitions(stage_code: str) -> list[str]:
    """Return list of stage codes reachable from the given stage."""
    return ALLOWED_STAGE_TRANSITIONS.get(stage_code, [])


def register_new_deal(deal: Deal, actor: CustomUser) -> Deal:
    """
    Post-create hook for new deals: writes ActivityLog entry.

    The Deal itself is created by the ViewSet's perform_create
    (auto-assigning client, company, and DRAFT stage). This function
    records the audit trail so the ViewSet stays a thin wrapper
    (Rule 8).
    """
    ActivityLog.objects.create(
        action="Сделка создана",
        detail=(
            f"Пользователь {actor.email} инициировал "
            f"новую сделку #{deal.id} для компании "
            f"{deal.company.name if deal.company else 'N/A'}"
        ),
        user=actor,
        level='INFO',
    )
    return deal


def transition_deal_stage(
    deal: Deal,
    target_stage_code: str,
    actor: Optional[CustomUser] = None,
    reason: str = '',
    validate_fsm: bool = True,
    admin_override: bool = False,
) -> Tuple[Optional[Deal], Optional[str]]:
    """
    Transition a Deal to a new stage by stage code.

    When validate_fsm=True, enforces the FSM transition matrix.
    admin_override=True allows Platform Admin to bypass both the FSM and the
    is_platform_admin_viewer guard. Use only from force_transition_deal_stage.
    Logs the change to ActivityLog.
    Returns: (deal, error_or_None)
    """
    # Actor-guard: when called by a real user (not internal/system), block
    # platform-admin viewers. Internal callers (auto-tasks, smoke scripts) pass
    # actor=None and bypass this check intentionally. admin_override also
    # bypasses: that path requires a reason and is itself a platform admin act.
    if actor is not None and not admin_override:
        from accounts.services import is_platform_admin_viewer
        if is_platform_admin_viewer(actor):
            return None, 'ADMIN_VIEWER_CANNOT_ACT'

    target_stage = DealStage.objects.filter(code=target_stage_code).first()
    if not target_stage:
        return None, 'DEAL_STAGE_NOT_FOUND'

    if deal.stage and deal.stage.code == target_stage_code:
        return deal, None  # already in target state, no-op

    if validate_fsm:
        current_code = deal.stage.code if deal.stage else 'DRAFT'
        allowed = get_allowed_transitions(current_code)
        if target_stage_code not in allowed:
            allowed_str = ', '.join(allowed) if allowed else 'none (terminal state)'
            return None, 'FSM_TRANSITION_NOT_ALLOWED'

    # Contract gate: CLOSED_WON requires a fully signed Contract.
    if validate_fsm and target_stage_code in STAGE_REQUIRES_SIGNED_CONTRACT:
        has_signed = deal.contracts.filter(status='SIGNED').exists()
        if not has_signed:
            return None, 'CLOSED_WON_REQUIRES_SIGNED_CONTRACT'

    old_stage_code = deal.stage.code if deal.stage else ''
    old_stage_name = deal.stage.name if deal.stage else '—'
    deal.stage = target_stage
    deal.save(update_fields=['stage'])

    from core.audit import log_admin_action
    log_admin_action(
        entity_type='deal',
        entity_id=deal.id,
        action='Стадия изменена' if validate_fsm else 'Force: стадия изменена',
        detail=f"Сделка #{deal.id}: {old_stage_name} → {target_stage.name}",
        actor=actor,
        reason=reason,
        before={'stage_code': old_stage_code, 'stage_name': old_stage_name},
        after={'stage_code': target_stage.code, 'stage_name': target_stage.name},
        level='WARNING' if not validate_fsm else 'INFO',
    )

    # Post-sale hook: on CLOSED_WON, auto-generate Invoice + Act (async)
    if target_stage_code == 'CLOSED_WON':
        try:
            from .tasks import auto_invoice_on_closed_won
            auto_invoice_on_closed_won.delay(deal.id)
        except Exception:
            logger.exception('Failed to dispatch auto-invoice task for deal %s', deal.id)

    return deal, None


def force_transition_deal_stage(
    deal: Deal,
    target_stage_code: str,
    actor: Optional[CustomUser] = None,
    reason: str = '',
) -> Tuple[Optional[Deal], Optional[str]]:
    """
    Platform-admin override: bypasses the FSM but REQUIRES a non-empty reason.
    Must be called only from the admin force-stage endpoint.
    """
    if not (reason or '').strip():
        return None, 'REASON_REQUIRED'
    return transition_deal_stage(
        deal=deal,
        target_stage_code=target_stage_code,
        actor=actor,
        reason=reason,
        validate_fsm=False,
        admin_override=True,
    )


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


def archive_messages_sync(messages: QuerySet[Message]) -> dict:
    """Move a specific set of deal-chat messages to S3 cold storage synchronously.

    Shares the JSONL format with the Celery task `crm.tasks.archive_old_messages`
    (same `_archive_path_for` + `_serialize_message`), so archives from the
    admin emergency action and the scheduled task are interleaved in the
    same daily files.

    Skips already-archived rows. Returns a summary dict:
        {'archived': <int>, 'files': <int>, 'errors': [str, ...]}
    """
    import json

    from django.core.files.base import ContentFile
    from django.utils import timezone

    from core.storage import get_private_storage

    from .tasks import _archive_path_for, _serialize_message

    storage = get_private_storage()
    pending = list(messages.filter(is_archived=False).select_related('sender'))
    if not pending:
        return {'archived': 0, 'files': 0, 'errors': []}

    groups: dict = {}
    for msg in pending:
        path = _archive_path_for(msg.timestamp.date())
        groups.setdefault(path, []).append(msg)

    archived = 0
    errors: list[str] = []
    for path, group_msgs in groups.items():
        jsonl = '\n'.join(
            json.dumps(_serialize_message(m), ensure_ascii=False) for m in group_msgs
        ) + '\n'
        try:
            if storage.exists(path):
                with storage.open(path, 'rb') as f:
                    existing = f.read().decode('utf-8')
                content = existing + jsonl
                storage.delete(path)
            else:
                content = jsonl
            storage.save(path, ContentFile(content.encode('utf-8')))
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue

        Message.objects.filter(id__in=[m.id for m in group_msgs]).update(
            is_archived=True,
            archived_at=timezone.now(),
            archive_path=path,
        )
        archived += len(group_msgs)

    return {'archived': archived, 'files': len(groups) - len(errors), 'errors': errors}


@transaction.atomic
def convert_lead_to_deal(
    lead: Lead, actor: CustomUser, company: Optional[Company] = None,
) -> Tuple[Optional[Deal], Optional[str]]:
    """Convert a Lead into a Deal in DRAFT stage.

    If `company` is not provided, tries to resolve one via the lead email.
    """
    from accounts.services import is_platform_admin_viewer
    if is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    if lead.is_processed:
        return None, 'LEAD_ALREADY_PROCESSED'

    if company is None:
        company = Company.objects.filter(
            members__user__email__iexact=lead.email, members__is_active=True,
        ).first()
    if company is None:
        return None, 'LEAD_NO_CLIENT_COMPANY'

    draft_stage = DealStage.objects.filter(code='DRAFT').first()
    deal = Deal.objects.create(
        company=company,
        client=CustomUser.objects.filter(email__iexact=lead.email).first(),
        manager=actor if (actor and actor.is_platform_admin) else None,
        stage=draft_stage,
        title=(lead.message[:200] if lead.message else f"Лид: {lead.name}"),
        notes=f"Создано из Lead #{lead.id}\nEmail: {lead.email}\nТелефон: {lead.phone}",
    )
    lead.is_processed = True
    lead.save(update_fields=['is_processed'])

    ActivityLog.objects.create(
        action="Lead конвертирован в сделку",
        detail=f"Lead #{lead.id} → Deal #{deal.id}",
        user=actor, level='SUCCESS',
    )
    return deal, None


# ──────────────────────────────────────────────────────────────────────────
# Contracts
# ──────────────────────────────────────────────────────────────────────────


def _next_contract_number() -> str:
    from django.utils import timezone
    from .models import Contract
    today = timezone.now()
    count = Contract.objects.filter(created_at__year=today.year).count() + 1
    return f"CT-{today.year}-{count:05d}"


@transaction.atomic
def generate_contract_from_quote(
    quote_id: int, actor: Optional[CustomUser] = None, notes: str = '',
) -> Tuple[Optional['Contract'], Optional[str]]:
    """Create a Contract tied to an approved Quote, render its PDF."""
    from accounts.services import is_platform_admin_viewer
    from .models import Contract
    if actor is not None and is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    quote = Quote.objects.select_related('deal__company', 'status').get(pk=quote_id)

    if not quote.status or quote.status.code not in {'APPROVED', 'SENT'}:
        return None, 'CONTRACT_NEEDS_APPROVAL'

    # Reuse existing draft contract if present
    contract = Contract.objects.filter(deal=quote.deal, quote=quote).exclude(
        status__in=['CANCELLED'],
    ).order_by('-created_at').first()

    if not contract:
        contract = Contract(
            deal=quote.deal,
            quote=quote,
            number=_next_contract_number(),
            status='DRAFT',
            total_amount=quote.total_incl_vat,
            currency=quote.items.first().frozen_currency if quote.items.exists() else None,
            created_by=actor,
            notes=notes,
        )
        contract.save()

    # Render PDF
    _render_contract_pdf(contract)

    contract.status = 'PENDING_CLIENT' if contract.status == 'DRAFT' else contract.status
    contract.save(update_fields=['status', 'pdf_file', 'updated_at'])

    ActivityLog.objects.create(
        action="Создан контракт",
        detail=f"Контракт {contract.number} по сделке #{quote.deal_id}",
        user=actor, level='INFO',
    )
    return contract, None


def _render_contract_pdf(contract) -> None:
    from django.template.loader import render_to_string
    from weasyprint import HTML
    from io import BytesIO
    from django.core.files.base import ContentFile

    html_string = render_to_string('crm/contract_pdf.html', {
        'contract': contract,
        'deal': contract.deal,
        'company': contract.deal.company,
        'quote': contract.quote,
        'items': contract.quote.items.select_related('product', 'frozen_currency').all(),
    })
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    filename = f"Contract_{contract.number}.pdf"
    contract.pdf_file.save(filename, ContentFile(buf.getvalue()), save=True)


@transaction.atomic
def sign_contract_by_client(
    contract_id: int, client_user: CustomUser,
) -> Tuple[Optional['Contract'], Optional[str]]:
    """Click-to-sign by client. MANUAL MODE — to be replaced by E-IMZO/DocuSign.
    See memory `tech_debt_payment_esign.md`.
    """
    from django.utils import timezone
    from accounts.services import is_member_of, is_platform_admin_viewer
    from .models import Contract
    contract = Contract.objects.select_for_update().select_related('deal').get(pk=contract_id)
    if is_platform_admin_viewer(client_user):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    if not (getattr(client_user, 'is_superuser', False)
            or is_member_of(client_user, contract.deal.company_id, capability='buy')):
        return None, 'MEMBER_REQUIRED_FOR_ACTION'
    if contract.status not in {'DRAFT', 'PENDING_CLIENT'}:
        return None, 'CONTRACT_CLIENT_SIGN_NOT_ALLOWED'
    contract.client_signer = client_user
    contract.client_signed_at = timezone.now()
    contract.status = 'PENDING_MANAGER' if not contract.manager_signed_at else 'SIGNED'
    contract.save(update_fields=['client_signer', 'client_signed_at', 'status', 'updated_at'])
    ActivityLog.objects.create(
        action="[MANUAL_MODE] Подписан контракт (сторона клиента)",
        detail=f"Контракт {contract.number} / сделка #{contract.deal_id}",
        user=client_user, level='INFO',
    )
    _notify_contract_signed(contract)
    return contract, None


@transaction.atomic
def sign_contract_by_manager(
    contract_id: int, manager_user: CustomUser,
) -> Tuple[Optional['Contract'], Optional[str]]:
    """Click-to-sign by seller-side company manager. MANUAL MODE — to be replaced by E-IMZO.
    See memory `tech_debt_payment_esign.md`.

    Seller side is represented by the accepted SupplierBid's supplier company
    (if any) or — when a deal has no bid — by any member with can_sell on the
    deal.company itself (self-service intra-company deals).
    """
    from django.utils import timezone
    from accounts.services import is_member_of, is_platform_admin_viewer
    from .models import Contract, SupplierBid
    contract = Contract.objects.select_for_update().select_related('deal').get(pk=contract_id)
    if is_platform_admin_viewer(manager_user):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    seller_company_ids = list(
        SupplierBid.objects.filter(deal_id=contract.deal_id, status='ACCEPTED')
        .values_list('supplier_id', flat=True),
    )
    seller_company_ids.append(contract.deal.company_id)  # intra-company fallback
    authorized = getattr(manager_user, 'is_superuser', False) or any(
        is_member_of(manager_user, cid, capability='sell') for cid in seller_company_ids
    )
    if not authorized:
        return None, 'MEMBER_REQUIRED_FOR_ACTION'
    if contract.status not in {'DRAFT', 'PENDING_MANAGER', 'PENDING_CLIENT'}:
        return None, 'CONTRACT_MANAGER_SIGN_NOT_ALLOWED'
    contract.manager_signer = manager_user
    contract.manager_signed_at = timezone.now()
    contract.status = 'SIGNED' if contract.client_signed_at else 'PENDING_CLIENT'
    contract.save(update_fields=['manager_signer', 'manager_signed_at', 'status', 'updated_at'])
    ActivityLog.objects.create(
        action="[MANUAL_MODE] Подписан контракт (сторона RailTech)",
        detail=f"Контракт {contract.number} / сделка #{contract.deal_id}",
        user=manager_user, level='INFO',
    )
    _notify_contract_signed(contract)
    return contract, None


def _notify_contract_signed(contract) -> None:
    from notifications.models import Notification, NotificationType
    if contract.status != 'SIGNED':
        return
    info = NotificationType.objects.filter(code='SUCCESS').first()
    for recipient in {contract.deal.client, contract.deal.manager}:
        if recipient is None:
            continue
        Notification.objects.create(
            user=recipient, type=info,
            title="Контракт подписан",
            message=f"Контракт {contract.number} по сделке #{contract.deal_id} подписан обеими сторонами",
            link="/crm/deals",
            deal=contract.deal,
        )


@transaction.atomic
def cancel_contract(contract_id: int, actor: CustomUser, reason: str = '') -> Tuple[Optional['Contract'], Optional[str]]:
    from accounts.services import is_platform_admin_viewer
    from .models import Contract
    if is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    contract = Contract.objects.select_for_update().get(pk=contract_id)
    if contract.status == 'SIGNED':
        return None, 'CONTRACT_SIGNED_CANNOT_CANCEL'
    contract.status = 'CANCELLED'
    contract.notes = f"{contract.notes}\nОтменён {actor}: {reason}".strip()
    contract.save(update_fields=['status', 'notes', 'updated_at'])
    return contract, None


@transaction.atomic
def force_cancel_contract(
    contract_id: int, admin_user: CustomUser, reason: str = '',
) -> Tuple[Optional['Contract'], Optional[str]]:
    """Platform-admin force override: cancel a contract regardless of its status.

    Used for escalations (e.g. fraud, court order, mutual annulment after signing).
    Logged with [FORCE_ADMIN] marker. Reason is mandatory for audit. Viewer-mode
    admins are permitted — force-actions are platform-admin moderation, not bound
    to a CompanyMember.
    """
    from .models import Contract
    if not (getattr(admin_user, 'is_superuser', False)
            or (admin_user.role and admin_user.role.code == 'ADMIN')):
        return None, 'PLATFORM_ADMIN_REQUIRED'
    if not reason.strip():
        return None, 'FORCE_REASON_REQUIRED'
    contract = Contract.objects.select_for_update().get(pk=contract_id)
    old_status = contract.status
    contract.status = 'CANCELLED'
    contract.notes = (
        f"{contract.notes}\n[FORCE_ADMIN] {admin_user.email}: {reason}"
        if contract.notes else f"[FORCE_ADMIN] {admin_user.email}: {reason}"
    )
    contract.save(update_fields=['status', 'notes', 'updated_at'])
    ActivityLog.objects.create(
        action="[FORCE_ADMIN] Контракт отменён платформенным админом",
        detail=f"Контракт #{contract_id} ({old_status} → CANCELLED). Причина: {reason}",
        user=admin_user, level='WARNING',
    )
    return contract, None


# ──────────────────────────────────────────────────────────────────────────
# Invoices, Payments, Acts
# ──────────────────────────────────────────────────────────────────────────


def _next_invoice_number() -> str:
    from django.utils import timezone
    from .models import Invoice
    today = timezone.now()
    count = Invoice.objects.filter(created_at__year=today.year).count() + 1
    return f"INV-{today.year}-{count:05d}"


def _next_act_number() -> str:
    from django.utils import timezone
    from .models import Act
    today = timezone.now()
    count = Act.objects.filter(created_at__year=today.year).count() + 1
    return f"ACT-{today.year}-{count:05d}"


@transaction.atomic
def generate_invoice_from_contract(
    contract_id: int, actor: Optional[CustomUser] = None, due_days: int = 14,
) -> Tuple[Optional['Invoice'], Optional[str]]:
    from datetime import timedelta
    from django.utils import timezone
    from accounts.services import is_platform_admin_viewer
    from .models import Contract, Invoice, InvoiceItem
    if actor is not None and is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    contract = Contract.objects.select_related('quote__deal').get(pk=contract_id)

    if contract.status != 'SIGNED':
        return None, 'INVOICE_REQUIRES_SIGNED_CONTRACT'

    quote = contract.quote
    invoice = Invoice.objects.create(
        deal=contract.deal, contract=contract,
        number=_next_invoice_number(),
        status='ISSUED',
        issued_at=timezone.now().date(),
        due_date=(timezone.now() + timedelta(days=due_days)).date(),
        subtotal_excl_vat=quote.subtotal_excl_vat,
        vat_amount=quote.vat_amount,
        total_incl_vat=quote.total_incl_vat,
        currency=quote.items.first().frozen_currency if quote.items.exists() else None,
        created_by=actor,
    )

    for qi in quote.items.select_related('product').all():
        InvoiceItem.objects.create(
            invoice=invoice,
            description=(qi.product.name if qi.product else qi.imported_raw_name) or 'Позиция',
            quantity=qi.quantity,
            unit_price_excl_vat=qi.final_price_excl_vat,
            line_total_excl_vat=(qi.final_price_excl_vat * qi.quantity),
            source_quote_item=qi,
        )

    _render_invoice_pdf(invoice)
    ActivityLog.objects.create(
        action="Инвойс выставлен",
        detail=f"Инвойс {invoice.number} по сделке #{invoice.deal_id}",
        user=actor, level='INFO',
    )
    return invoice, None


def _render_invoice_pdf(invoice) -> None:
    from django.template.loader import render_to_string
    from weasyprint import HTML
    from io import BytesIO
    from django.core.files.base import ContentFile
    html_string = render_to_string('crm/invoice_pdf.html', {
        'invoice': invoice,
        'items': invoice.items.select_related('source_quote_item').all(),
        'company': invoice.deal.company,
    })
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    invoice.pdf_file.save(f"Invoice_{invoice.number}.pdf", ContentFile(buf.getvalue()), save=True)


@transaction.atomic
def record_payment(
    payment_data_or_invoice_id, actor: CustomUser, amount=None, paid_at=None,
    method: str = 'BANK_TRANSFER', reference: str = '', proof_file=None,
    manual: bool = True,
) -> Tuple[Optional[object], Optional[str]]:
    """Record payment against an invoice.

    Accepts either a PaymentData dataclass or positional/keyword args for
    backwards compatibility. New callers should prefer PaymentData.

    NOTE: manual=True marks the record as hand-entered (no payment-provider webhook).
    Logged with [MANUAL_MODE] tag in ActivityLog -- needed for later reconciliation
    once Click/Payme/Stripe webhooks replace the manual flow. See memory
    `tech_debt_payment_esign.md`.
    """
    # Unpack PaymentData if provided
    if isinstance(payment_data_or_invoice_id, PaymentData):
        pd = payment_data_or_invoice_id
        invoice_id = pd.invoice_id
        amount = pd.amount
        paid_at = pd.paid_at
        method = pd.method
        reference = pd.reference
        proof_file = pd.proof_file
        manual = pd.manual
    else:
        invoice_id = payment_data_or_invoice_id

    from decimal import Decimal as D
    from accounts.services import is_member_of, is_platform_admin_viewer
    from .models import Invoice, Payment
    invoice = Invoice.objects.select_for_update().select_related('deal').get(pk=invoice_id)
    # Actor-guard: platform-admin viewer cannot execute business actions.
    if is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    # Payment is recorded by the buyer side of the deal -- must be member w/ can_buy.
    if not (getattr(actor, 'is_superuser', False)
            or is_member_of(actor, invoice.deal.company_id, capability='buy')):
        return None, 'MEMBER_REQUIRED_FOR_ACTION'
    if invoice.status in {'CANCELLED'}:
        return None, 'INVOICE_CANCELLED'
    amount_d = D(str(amount))
    if amount_d <= 0:
        return None, 'PAYMENT_AMOUNT_MUST_BE_POSITIVE'

    if proof_file:
        from core.validators import validate_document_upload
        validate_document_upload(proof_file)

    payment = Payment.objects.create(
        invoice=invoice, amount=amount_d, method=method,
        paid_at=paid_at, reference=reference, proof_file=proof_file,
        recorded_by=actor,
    )

    invoice.amount_paid = (invoice.amount_paid or D('0')) + amount_d
    if invoice.amount_paid >= invoice.total_incl_vat:
        invoice.status = 'PAID'
    else:
        invoice.status = 'PARTIAL'
    invoice.save(update_fields=['amount_paid', 'status', 'updated_at'])

    marker = '[MANUAL_MODE] ' if manual else ''
    ActivityLog.objects.create(
        action=f"{marker}Зафиксирован платёж",
        detail=f"Инвойс {invoice.number}: получено {amount_d} (итого {invoice.amount_paid}/{invoice.total_incl_vat})",
        user=actor, level='SUCCESS',
    )
    return payment, None


@transaction.atomic
def generate_act(
    invoice_id: int, actor: Optional[CustomUser] = None,
) -> Tuple[Optional[object], Optional[str]]:
    from django.utils import timezone
    from accounts.services import is_platform_admin_viewer
    from .models import Invoice, Act
    if actor is not None and is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    invoice = Invoice.objects.select_related('contract', 'deal').get(pk=invoice_id)
    if invoice.status not in {'PAID', 'PARTIAL', 'ISSUED'}:
        return None, 'ACT_INVALID_INVOICE_STATUS'

    act = Act.objects.create(
        deal=invoice.deal, contract=invoice.contract, invoice=invoice,
        number=_next_act_number(),
        status='ISSUED',
        issued_at=timezone.now().date(),
        total_amount=invoice.total_incl_vat,
        created_by=actor,
    )
    _render_act_pdf(act)
    return act, None


def _render_act_pdf(act) -> None:
    from django.template.loader import render_to_string
    from weasyprint import HTML
    from io import BytesIO
    from django.core.files.base import ContentFile
    html_string = render_to_string('crm/act_pdf.html', {
        'act': act, 'invoice': act.invoice, 'company': act.deal.company,
    })
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    act.pdf_file.save(f"Act_{act.number}.pdf", ContentFile(buf.getvalue()), save=True)


@transaction.atomic
def sign_act(act_id: int, actor: CustomUser, signed_file=None) -> Tuple[Optional[object], Optional[str]]:
    from django.utils import timezone
    from accounts.services import is_platform_admin_viewer
    from .models import Act
    if is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    act = Act.objects.select_for_update().get(pk=act_id)
    if act.status != 'ISSUED':
        return None, 'ACT_SIGN_NOT_ALLOWED'
    act.status = 'SIGNED'
    act.signed_at = timezone.now()
    if signed_file is not None:
        act.signed_file = signed_file
    act.save(update_fields=['status', 'signed_at', 'signed_file', 'updated_at'])
    return act, None


# ──────────────────────────────────────────────────────────────────────────
# Fulfillment (post-sale)
# ──────────────────────────────────────────────────────────────────────────


@transaction.atomic
def ensure_fulfillment(deal: Deal) -> object:
    from .models import Fulfillment
    obj, _ = Fulfillment.objects.get_or_create(deal=deal)
    return obj


@transaction.atomic
def update_fulfillment_status(
    deal_id: int, actor: CustomUser, status_code: str, **extra,
) -> Tuple[Optional[object], Optional[str]]:
    from django.utils import timezone
    from accounts.services import is_platform_admin_viewer
    from .models import Fulfillment
    if is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    valid = {'PENDING', 'SHIPPED', 'IN_TRANSIT', 'DELIVERED', 'ACCEPTED', 'DISPUTED'}
    if status_code not in valid:
        return None, 'FULFILLMENT_INVALID_STATUS'
    obj = Fulfillment.objects.select_for_update().select_related('deal').get(deal_id=deal_id)
    obj.status = status_code
    now = timezone.now()
    if status_code == 'SHIPPED' and not obj.shipped_at:
        obj.shipped_at = now
    if status_code == 'DELIVERED' and not obj.delivered_at:
        obj.delivered_at = now
    if status_code == 'ACCEPTED' and not obj.accepted_at:
        obj.accepted_at = now
    for key in ('tracking_number', 'carrier', 'expected_delivery_date', 'notes'):
        if key in extra and extra[key] is not None:
            setattr(obj, key, extra[key])
    obj.save()
    # Auto-close deal when accepted by client
    if status_code == 'ACCEPTED':
        transition_deal_stage(obj.deal, 'CLOSED_WON', actor=actor, reason="Приёмка клиентом")
    return obj, None


# ──────────────────────────────────────────────────────────────────────────
# Supplier bidding
# ──────────────────────────────────────────────────────────────────────────


@transaction.atomic
def open_rfq(
    deal_id: int, actor: CustomUser, supplier_ids: Optional[list[int]] = None,
) -> Tuple[Optional[Deal], Optional[str]]:
    """Move deal into RFQ_OPEN and notify invited suppliers."""
    from accounts.services import is_member_of, is_platform_admin_viewer
    from notifications.models import Notification, NotificationType
    if is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    deal = Deal.objects.select_for_update().get(pk=deal_id)
    # RFQ is buyer-side: must be a can_buy member of the deal company.
    if not (getattr(actor, 'is_superuser', False)
            or is_member_of(actor, deal.company_id, capability='buy')):
        return None, 'MEMBER_REQUIRED_FOR_ACTION'

    deal, err = transition_deal_stage(deal, 'RFQ_OPEN', actor=actor, reason="Открыт RFQ")
    if err:
        return None, err

    if supplier_ids:
        info = NotificationType.objects.filter(code='INFO').first()
        from accounts.models import CompanyMember
        target_users = CustomUser.objects.filter(
            memberships__company_id__in=supplier_ids,
            memberships__is_active=True,
        ).distinct()
        for u in target_users:
            Notification.objects.create(
                user=u, type=info,
                title="Новый RFQ",
                message=f"Откройте сделку #{deal_id} и подайте предложение",
                link=f"/crm/deals/{deal_id}",
                deal=deal,
            )
    return deal, None


@transaction.atomic
def submit_supplier_bid(
    bid_or_deal_id, supplier_id: Optional[int] = None,
    submitted_by: Optional[CustomUser] = None,
    items: Optional[list[dict]] = None, notes: str = '',
    lead_time_days: Optional[int] = None,
    currency_id: Optional[int] = None,
) -> Tuple[Optional[object], Optional[str]]:
    """Create or update a SupplierBid for the given deal+supplier.

    Accepts either a BidSubmission dataclass or positional/keyword args for
    backwards compatibility. New callers should prefer BidSubmission.
    """
    # Unpack BidSubmission if provided
    if isinstance(bid_or_deal_id, BidSubmission):
        bs = bid_or_deal_id
        deal_id = bs.deal_id
        supplier_id = bs.supplier_id
        items = bs.items
        notes = bs.notes
        lead_time_days = bs.lead_time_days
        currency_id = bs.currency_id
    else:
        deal_id = bid_or_deal_id
    if items is None:
        items = []

    from decimal import Decimal as D
    from django.utils import timezone
    from accounts.services import (
        company_has_operational_subscription, is_member_of, is_platform_admin_viewer,
    )
    from .models import SupplierBid, SupplierBidItem
    if is_platform_admin_viewer(submitted_by):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    deal = Deal.objects.get(pk=deal_id)
    if deal.stage and deal.stage.code not in {'RFQ_OPEN'}:
        return None, 'BID_ONLY_IN_RFQ_OPEN'
    # Security: user must be active member of the supplier company with can_sell.
    if not (getattr(submitted_by, 'is_superuser', False)
            or is_member_of(submitted_by, supplier_id, capability='sell')):
        return None, 'NOT_A_SUPPLIER_MEMBER'
    # Feature gate: supplier company must have an operational subscription.
    # Superusers bypass for emergency fixes only.
    if not (getattr(submitted_by, 'is_superuser', False)
            or company_has_operational_subscription(supplier_id)):
        return None, 'SUBSCRIPTION_NOT_OPERATIONAL'
    bid, _ = SupplierBid.objects.get_or_create(deal_id=deal_id, supplier_id=supplier_id)
    bid.items.all().delete()
    total = D('0')
    for row in items:
        qty = int(row.get('quantity', 1) or 1)
        price = D(str(row.get('unit_price', 0) or 0))
        SupplierBidItem.objects.create(
            bid=bid,
            quote_item_id=row.get('quote_item_id'),
            product_id=row.get('product_id'),
            description=row.get('description', ''),
            quantity=qty,
            unit_price=price,
            lead_time_days=row.get('lead_time_days'),
        )
        total += price * qty
    bid.submitted_by = submitted_by
    bid.status = 'SUBMITTED'
    bid.submitted_at = timezone.now()
    bid.total_amount = total
    bid.lead_time_days = lead_time_days
    if currency_id:
        bid.currency_id = currency_id
    bid.notes = notes
    bid.save()

    # Audit -- log to BOTH the bid itself and the parent deal so admin timeline
    # on a deal surfaces supplier actions.
    from core.audit import log_admin_action
    snapshot = {
        'status': bid.status,
        'total_amount': str(bid.total_amount),
        'lead_time_days': bid.lead_time_days,
        'items_count': bid.items.count(),
    }
    log_admin_action(
        entity_type='supplier_bid',
        entity_id=bid.id,
        action='SupplierBid submitted',
        detail=f"Deal #{deal_id} · supplier #{supplier_id} · {bid.total_amount}",
        actor=submitted_by,
        after=snapshot,
        level='INFO',
    )
    log_admin_action(
        entity_type='deal',
        entity_id=deal_id,
        action=f'SupplierBid #{bid.id} submitted',
        detail=f"supplier #{supplier_id} · {bid.total_amount}",
        actor=submitted_by,
        after=snapshot,
        level='INFO',
    )
    return bid, None


@transaction.atomic
def accept_supplier_bid(
    bid_id: int, actor: CustomUser,
) -> Tuple[Optional[object], Optional[str]]:
    from django.utils import timezone
    from .models import SupplierBid
    bid = SupplierBid.objects.select_for_update().select_related('deal').get(pk=bid_id)
    if bid.status != 'SUBMITTED':
        return None, 'BID_ACCEPT_NOT_ALLOWED'
    before_status = bid.status
    bid.status = 'ACCEPTED'
    bid.accepted_at = timezone.now()
    bid.save(update_fields=['status', 'accepted_at', 'updated_at'])
    # Reject competitors
    rejected_count = SupplierBid.objects.filter(deal=bid.deal).exclude(pk=bid.pk).filter(
        status='SUBMITTED',
    ).update(status='REJECTED')
    transition_deal_stage(bid.deal, 'CALCULATING', actor=actor, reason=f"Принят bid #{bid.id}")

    from core.audit import log_admin_action
    log_admin_action(
        entity_type='supplier_bid',
        entity_id=bid.id,
        action='SupplierBid accepted',
        detail=f"Deal #{bid.deal_id} · rejected {rejected_count} competing bid(s)",
        actor=actor,
        before={'status': before_status},
        after={'status': 'ACCEPTED'},
        level='SUCCESS',
    )
    log_admin_action(
        entity_type='deal',
        entity_id=bid.deal_id,
        action=f'SupplierBid #{bid.id} accepted',
        detail=f"competing bids auto-rejected: {rejected_count}",
        actor=actor,
        after={'status': 'ACCEPTED'},
        level='SUCCESS',
    )
    return bid, None


@transaction.atomic
def reject_supplier_bid(
    bid_id: int, actor: CustomUser, reason: str = '',
) -> Tuple[Optional[object], Optional[str]]:
    from .models import SupplierBid
    bid = SupplierBid.objects.select_for_update().get(pk=bid_id)
    if bid.status not in {'SUBMITTED', 'DRAFT'}:
        return None, 'BID_REJECT_NOT_ALLOWED'
    before_status = bid.status
    bid.status = 'REJECTED'
    if reason:
        bid.notes = f"{bid.notes}\nОтклонено: {reason}".strip()
    bid.save(update_fields=['status', 'notes', 'updated_at'])

    from core.audit import log_admin_action
    log_admin_action(
        entity_type='supplier_bid',
        entity_id=bid.id,
        action='SupplierBid rejected',
        detail=f"Deal #{bid.deal_id} · supplier #{bid.supplier_id}",
        actor=actor,
        reason=reason,
        before={'status': before_status},
        after={'status': 'REJECTED'},
        level='WARNING',
    )
    log_admin_action(
        entity_type='deal',
        entity_id=bid.deal_id,
        action=f'SupplierBid #{bid.id} rejected',
        detail=f"supplier #{bid.supplier_id}",
        actor=actor,
        reason=reason,
        level='WARNING',
    )
    return bid, None


# ──────────────────────────────────────────────────────────────────────────
# Re-match (manual reassign QuoteItem.product)
# ──────────────────────────────────────────────────────────────────────────


@transaction.atomic
def reassign_quote_item_product(
    quote_item_id: int, actor: CustomUser, product_id: Optional[int],
) -> Tuple[Optional[QuoteItem], Optional[str]]:
    """Allow manager to override Smart Match result by picking a different product."""
    from accounts.services import is_platform_admin_viewer
    from catalog.models import Product
    if is_platform_admin_viewer(actor):
        return None, 'ADMIN_VIEWER_CANNOT_ACT'
    item = QuoteItem.objects.select_for_update().select_related('quote').get(pk=quote_item_id)
    if item.quote.frozen_at:
        return None, 'QUOTE_FROZEN_CANNOT_REASSIGN'
    if product_id:
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            return None, 'PRODUCT_NOT_FOUND'
        item.product = product
    else:
        item.product = None
    item.save(update_fields=['product', 'assigned_at'])
    ActivityLog.objects.create(
        action="Переназначен продукт в позиции КП",
        detail=f"QuoteItem #{item.id} → Product #{product_id}",
        user=actor, level='INFO',
    )
    return item, None


MAX_MESSAGE_LENGTH = 5000


def user_can_access_deal_chat(user: CustomUser, deal: Deal) -> bool:
    """Platform admin, deal manager, deal client, or any active member of deal.company."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_platform_admin', False):
        return True
    if deal.manager_id == user.id or deal.client_id == user.id:
        return True
    if deal.company_id:
        return user.memberships.filter(
            company_id=deal.company_id, is_active=True
        ).exists()
    return False


def send_deal_message(user: CustomUser, deal: Deal, text: str) -> Tuple[Optional[Message], Optional[str]]:
    """
    Create a chat message for a deal after authorization + validation.
    Broadcast happens via Message post_save signal — do not group_send here.
    """
    if not user_can_access_deal_chat(user, deal):
        return None, 'NOT_DEAL_MEMBER'
    clean = (text or '').strip()
    if not clean:
        return None, 'EMPTY_MESSAGE'
    message = Message.objects.create(
        deal=deal,
        sender=user,
        text=clean[:MAX_MESSAGE_LENGTH],
    )

    # Audit: attach a short entry to the deal timeline so admin sees
    # who said what, without exposing the full chat log. Keep the detail
    # short; the full message stays in crm_message.
    from core.audit import log_admin_action
    preview = clean[:120] + ('…' if len(clean) > 120 else '')
    log_admin_action(
        entity_type='deal',
        entity_id=deal.id,
        action='Сообщение в чате сделки',
        detail=preview,
        actor=user,
        level='INFO',
    )
    return message, None
