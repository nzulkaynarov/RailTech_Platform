"""
Celery tasks for the CRM app.

Currently:
  - archive_old_messages: cold-storage move of Deal chat messages to S3/MinIO
    as JSONL files. Source of truth: ADR-0001 (Unfold = engineering inspection,
    history goes to S3).
"""
import json
import logging
from datetime import timedelta
from io import BytesIO

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from core.storage import get_private_storage

logger = logging.getLogger(__name__)


def _serialize_message(msg) -> dict:
    """Convert a Message instance to a dict suitable for JSONL archiving."""
    return {
        'id': msg.id,
        'deal_id': msg.deal_id,
        'sender_id': msg.sender_id,
        'sender_email': getattr(msg.sender, 'email', None),
        'sender_full_name': msg.sender.get_full_name() if msg.sender else None,
        'text': msg.text,
        'message_type': msg.message_type,
        'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
    }


def _archive_path_for(date) -> str:
    """Generate S3 archive path for a given date.

    Format: archive/messages/{year}/{month}/{day}.jsonl
    """
    return f"archive/messages/{date.year:04d}/{date.month:02d}/{date.day:02d}.jsonl"


@shared_task(bind=True, name='crm.archive_old_messages')
def archive_old_messages(self, days: int = 90, batch_size: int = 500) -> dict:
    """
    Move messages older than `days` days to S3 cold storage.

    Strategy:
      1. Find non-archived messages older than the cutoff
      2. Group by date
      3. Append each group to a JSONL file in `archive/messages/YYYY/MM/DD.jsonl`
      4. Mark as `is_archived=True` with `archived_at` and `archive_path`
      5. Original DB rows are kept (lossless) so engineers can still inspect
         in Unfold; chat UI filters them out via `is_archived=False`.

    A separate purge task can later DELETE archived rows once verified.
    """
    from .models import Message  # local import to avoid app loading issues

    cutoff = timezone.now() - timedelta(days=days)
    storage = get_private_storage()

    queryset = (
        Message.objects
        .filter(timestamp__lt=cutoff, is_archived=False)
        .select_related('sender')
        .order_by('timestamp')
    )

    total = queryset.count()
    if total == 0:
        logger.info("archive_old_messages: nothing to archive")
        return {'status': 'no_messages', 'archived': 0}

    logger.info("archive_old_messages: %d messages to archive (cutoff=%s)", total, cutoff)

    archived_count = 0
    files_written: dict[str, int] = {}

    # Stream in batches to avoid loading huge resultsets into memory
    last_id = 0
    while True:
        batch = list(queryset.filter(id__gt=last_id)[:batch_size])
        if not batch:
            break

        # Group this batch by date and write JSONL append
        groups: dict[str, list] = {}
        for msg in batch:
            day = msg.timestamp.date()
            path = _archive_path_for(day)
            groups.setdefault(path, []).append(msg)

        for path, msgs in groups.items():
            jsonl = '\n'.join(json.dumps(_serialize_message(m), ensure_ascii=False) for m in msgs)
            jsonl += '\n'

            # Append-or-create: read existing content if any, append new lines
            try:
                if storage.exists(path):
                    with storage.open(path, 'rb') as f:
                        existing = f.read().decode('utf-8')
                    content = existing + jsonl
                else:
                    content = jsonl
            except Exception as e:
                logger.warning("archive_old_messages: failed to read %s: %s", path, e)
                content = jsonl

            # Save back (file_overwrite=False on backend → use save with delete first)
            try:
                if storage.exists(path):
                    storage.delete(path)
                storage.save(path, ContentFile(content.encode('utf-8')))
            except Exception as e:
                logger.error("archive_old_messages: failed to write %s: %s", path, e)
                continue

            files_written[path] = files_written.get(path, 0) + len(msgs)

            # Mark these messages as archived
            ids = [m.id for m in msgs]
            now = timezone.now()
            with transaction.atomic():
                Message.objects.filter(id__in=ids).update(
                    is_archived=True,
                    archived_at=now,
                    archive_path=path,
                )
            archived_count += len(msgs)

        last_id = batch[-1].id

    logger.info(
        "archive_old_messages: done — archived=%d files=%d",
        archived_count, len(files_written)
    )
    return {
        'status': 'success',
        'archived': archived_count,
        'files': files_written,
    }


@shared_task(name='crm.check_overdue_deliveries')
def check_overdue_deliveries() -> dict:
    """Flag fulfillments whose expected_delivery_date passed without status change.
    Sends in-app notification to the deal manager.
    """
    from .models import Fulfillment
    from notifications.models import Notification, NotificationType
    today = timezone.now().date()
    overdue_qs = Fulfillment.objects.filter(
        expected_delivery_date__lt=today,
        status__in=['PENDING', 'SHIPPED', 'IN_TRANSIT'],
    ).select_related('deal__manager')
    warn_type = NotificationType.objects.filter(code='WARNING').first()
    count = 0
    for ff in overdue_qs:
        mgr = ff.deal.manager
        if mgr:
            Notification.objects.create(
                user=mgr, type=warn_type,
                title='Просрочка по доставке',
                message=f'Сделка #{ff.deal_id}: ожидали {ff.expected_delivery_date}, статус {ff.status}',
                link='/crm/deals',
                deal=ff.deal,
            )
        count += 1
    return {'overdue_flagged': count}


@shared_task(name='crm.auto_invoice_on_closed_won')
def auto_invoice_on_closed_won(deal_id: int) -> dict:
    """Triggered after a deal transitions to CLOSED_WON: create invoice+act skeletons.

    Idempotent: safe to run multiple times for the same deal — reuses existing Invoice
    for the contract (if any) and existing Act for the invoice. Needed because:
      * transition_deal_stage may be called twice on a CLOSED_WON→CONTRACT_SIGNED→CLOSED_WON
        reopen loop;
      * Celery task retries duplicate the call.
    """
    from .models import Deal, Invoice, Act
    from .services import generate_invoice_from_contract, generate_act, ensure_fulfillment
    try:
        deal = Deal.objects.get(pk=deal_id)
    except Deal.DoesNotExist:
        return {'error': 'deal not found'}
    contract = deal.contracts.filter(status='SIGNED').order_by('-created_at').first()
    result = {'deal_id': deal_id, 'invoice': None, 'act': None, 'fulfillment': True,
              'idempotent_reuse': False}
    ensure_fulfillment(deal)
    if not contract:
        return result

    # Reuse existing Invoice for this contract if present (idempotency).
    invoice = Invoice.objects.filter(
        deal=deal, contract=contract,
    ).exclude(status='CANCELLED').order_by('-created_at').first()
    if invoice is None:
        invoice, err = generate_invoice_from_contract(contract.id)
        if invoice is None:
            return result
    else:
        result['idempotent_reuse'] = True
    result['invoice'] = invoice.id

    # Reuse existing Act for this invoice if present.
    act = Act.objects.filter(
        invoice=invoice,
    ).exclude(status='CANCELLED').order_by('-created_at').first()
    if act is None:
        act, err2 = generate_act(invoice.id)
    if act is not None:
        result['act'] = act.id
    return result
