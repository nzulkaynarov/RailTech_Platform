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

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from core.storage import get_private_storage

from .constants import ActStatusCode, ContractStatusCode, FulfillmentStatusCode, InvoiceStatusCode

logger = logging.getLogger(__name__)


def _serialize_message(msg) -> dict:
    """Convert a Message instance to a dict suitable for JSONL archiving."""
    return {
        "id": msg.id,
        "deal_id": msg.deal_id,
        "sender_id": msg.sender_id,
        "sender_email": getattr(msg.sender, "email", None),
        "sender_full_name": msg.sender.get_full_name() if msg.sender else None,
        "text": msg.text,
        "message_type": msg.message_type,
        "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
    }


def _archive_path_for(date) -> str:
    """Generate S3 archive path for a given date.

    Format: archive/messages/{year}/{month}/{day}.jsonl
    """
    return f"archive/messages/{date.year:04d}/{date.month:02d}/{date.day:02d}.jsonl"


@shared_task(
    bind=True,
    name="crm.archive_old_messages",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
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
        Message.objects.filter(timestamp__lt=cutoff, is_archived=False).select_related("sender").order_by("timestamp")
    )

    total = queryset.count()
    if total == 0:
        logger.info("archive_old_messages: nothing to archive")
        return {"status": "no_messages", "archived": 0}

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
            jsonl = "\n".join(json.dumps(_serialize_message(m), ensure_ascii=False) for m in msgs)
            jsonl += "\n"

            # Append-or-create: read existing content if any, append new lines
            try:
                if storage.exists(path):
                    with storage.open(path, "rb") as f:
                        existing = f.read().decode("utf-8")
                    content = existing + jsonl
                else:
                    content = jsonl
            except (IOError, OSError) as e:
                logger.warning("archive_old_messages: failed to read %s: %s", path, e)
                content = jsonl

            # Save back (file_overwrite=False on backend → use save with delete first)
            try:
                if storage.exists(path):
                    storage.delete(path)
                storage.save(path, ContentFile(content.encode("utf-8")))
            except (IOError, OSError) as e:
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

    logger.info("archive_old_messages: done — archived=%d files=%d", archived_count, len(files_written))
    return {
        "status": "success",
        "archived": archived_count,
        "files": files_written,
    }


@shared_task(
    bind=True,
    name="crm.check_overdue_deliveries",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def check_overdue_deliveries(self) -> dict:
    """Flag fulfillments whose expected_delivery_date passed without status change.
    Sends in-app notification to the deal manager.
    """
    from notifications.models import Notification, NotificationType

    from .models import Fulfillment

    today = timezone.now().date()
    overdue_qs = Fulfillment.objects.filter(
        expected_delivery_date__lt=today,
        # status is a FK now (F5.4) — match by the lookup's code.
        status__code__in=[
            FulfillmentStatusCode.PENDING,
            FulfillmentStatusCode.SHIPPED,
            FulfillmentStatusCode.IN_TRANSIT,
        ],
    ).select_related("deal__manager", "status")
    warn_type = NotificationType.objects.filter(code="WARNING").first()
    count = 0
    for ff in overdue_qs:
        mgr = ff.deal.manager
        if mgr:
            Notification.objects.create(
                user=mgr,
                type=warn_type,
                title="Просрочка по доставке",
                message=f"Сделка #{ff.deal_id}: ожидали {ff.expected_delivery_date}, статус {ff.status}",
                link="/crm/deals",
                deal=ff.deal,
            )
        count += 1
    return {"overdue_flagged": count}


@shared_task(
    bind=True,
    name="crm.auto_invoice_on_closed_won",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    # Financial task: ack only after completion and re-queue if the worker is
    # lost mid-run, so a SIGKILL/OOM/redeploy never silently drops invoice+act
    # creation. Safe because the task is idempotent (reuses existing Invoice/Act).
    # NB: the per-task attribute is `reject_on_worker_lost` (the *setting* is
    # `task_reject_on_worker_lost`).
    acks_late=True,
    reject_on_worker_lost=True,
)
def auto_invoice_on_closed_won(self, deal_id: int) -> dict:
    """Triggered after a deal transitions to CLOSED_WON: create invoice+act skeletons.

    Idempotent: safe to run multiple times for the same deal — reuses existing Invoice
    for the contract (if any) and existing Act for the invoice. Needed because:
      * transition_deal_stage may be called twice on a CLOSED_WON→CONTRACT_SIGNED→CLOSED_WON
        reopen loop;
      * Celery task retries duplicate the call.
    """
    from .models import Act, Deal, Invoice
    from .services import ensure_fulfillment, generate_act, generate_invoice_from_contract

    try:
        deal = Deal.objects.get(pk=deal_id)
    except Deal.DoesNotExist:
        return {"error": "deal not found"}
    contract = deal.contracts.filter(status__code=ContractStatusCode.SIGNED).order_by("-created_at").first()
    result = {"deal_id": deal_id, "invoice": None, "act": None, "fulfillment": True, "idempotent_reuse": False}
    ensure_fulfillment(deal)
    if not contract:
        return result

    # Reuse existing Invoice for this contract if present (idempotency).
    invoice = (
        Invoice.objects.filter(
            deal=deal,
            contract=contract,
        )
        .exclude(status__code=InvoiceStatusCode.CANCELLED)
        .order_by("-created_at")
        .first()
    )
    if invoice is None:
        invoice, err = generate_invoice_from_contract(contract.id)
        if invoice is None:
            return result
    else:
        result["idempotent_reuse"] = True
    result["invoice"] = invoice.id

    # Reuse existing Act for this invoice if present.
    act = (
        Act.objects.filter(
            invoice=invoice,
        )
        .exclude(status__code=ActStatusCode.CANCELLED)
        .order_by("-created_at")
        .first()
    )
    if act is None:
        act, err2 = generate_act(invoice.id)
    if act is not None:
        result["act"] = act.id
    return result


@shared_task(
    bind=True,
    name="crm.expire_stale_quotes",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def expire_stale_quotes(self) -> dict:
    """Move SENT quotes past `valid_until` to EXPIRED and notify the deal manager.

    Runs on a daily Beat schedule. Ignores DRAFT (not yet sent) and APPROVED /
    REJECTED (terminal) quotes. Each transition is audit-logged in ActivityLog.
    """
    from notifications.models import Notification, NotificationType

    from .models import ActivityLog, Quote, QuoteStatus

    today = timezone.now().date()
    expired_status = QuoteStatus.objects.filter(code="EXPIRED").first()
    if expired_status is None:
        logger.error("QuoteStatus 'EXPIRED' missing — seed migration not applied")
        return {"expired": 0, "error": "expired_status_missing"}
    stale_qs = Quote.objects.select_related("status", "deal__manager").filter(
        status__code="SENT",
        valid_until__isnull=False,
        valid_until__lt=today,
    )
    warn_type = NotificationType.objects.filter(code="WARNING").first()
    count = 0
    for q in stale_qs:
        q.status = expired_status
        q.save(update_fields=["status", "updated_at"])
        ActivityLog.objects.create(
            action="КП просрочено",
            detail=f"Quote #{q.id} v{q.version} (deal #{q.deal_id}) — valid_until={q.valid_until}",
            user=None,
            level="WARNING",
        )
        if q.deal.manager and warn_type:
            Notification.objects.create(
                user=q.deal.manager,
                type=warn_type,
                title="КП просрочено",
                message=f"Срок действия КП v{q.version} по сделке #{q.deal_id} истёк",
                link="/crm/quotes",
                deal=q.deal,
            )
        count += 1
    return {"expired": count}


# Render functions by document type. Each takes the model instance and writes its
# `pdf_file`. Kept as a dispatch map so the task and the lazy download fallback share
# one source of truth. The quote uses its lifecycle service (takes an id, not an obj).
def _render_pdf_for(doc_type: str, doc_id: int) -> None:
    from .models import Act, Contract, Invoice

    if doc_type == "contract":
        from .services.contracts import _render_contract_pdf

        _render_contract_pdf(Contract.objects.get(pk=doc_id))
    elif doc_type == "invoice":
        from .services.billing import _render_invoice_pdf

        _render_invoice_pdf(Invoice.objects.get(pk=doc_id))
    elif doc_type == "act":
        from .services.billing import _render_act_pdf

        _render_act_pdf(Act.objects.get(pk=doc_id))
    elif doc_type == "quote":
        from .services.quotes import QuoteLifecycleService

        QuoteLifecycleService.generate_pdf(doc_id)
    else:
        raise ValueError(f"Unknown PDF doc_type: {doc_type}")


@shared_task(
    bind=True,
    name="crm.render_document_pdf",
    queue="pdf",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def render_document_pdf(self, doc_type: str, doc_id: int) -> dict:
    """Render a document's PDF off the request thread.

    Scheduled via transaction.on_commit() at document creation, so the heavy
    WeasyPrint render never runs inside the creating transaction — eliminating the
    orphan-file-on-rollback class (a file written then abandoned by a rollback) and
    keeping the API response fast. The download endpoints render lazily on demand as
    a fallback, so a download that races ahead of this task still succeeds.
    """
    _render_pdf_for(doc_type, doc_id)
    logger.info("Rendered %s PDF for id=%s", doc_type, doc_id)
    return {"doc_type": doc_type, "doc_id": doc_id, "status": "rendered"}
