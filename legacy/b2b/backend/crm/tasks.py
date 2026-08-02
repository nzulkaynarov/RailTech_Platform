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
from django.utils import timezone, translation

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
    from .models import Fulfillment
    from .services.deal_notifications import notify_delivery_overdue

    today = timezone.now().date()
    overdue_qs = Fulfillment.objects.filter(
        expected_delivery_date__lt=today,
        # status is a FK now (F5.4) — match by the lookup's code.
        status__code__in=[
            FulfillmentStatusCode.PENDING,
            FulfillmentStatusCode.SHIPPED,
            FulfillmentStatusCode.IN_TRANSIT,
        ],
    ).select_related("deal__company", "status")

    # Раньше уведомление уходило одному `deal.manager` — legacy-полю, которое у реальных
    # сделок покупатель/продавец почти всегда пустое, а счётчик всё равно инкрементировался.
    # Задача рапортовала о работе, которой не делала; теперь извещаются обе стороны, а в
    # отчёте разделены просмотренные строки и фактически отправленные уведомления.
    overdue_count = 0
    notified = 0
    for fulfillment in overdue_qs:
        overdue_count += 1
        notified += notify_delivery_overdue(fulfillment)
    return {"overdue_flagged": overdue_count, "notified": notified}


@shared_task(
    bind=True,
    name="crm.auto_invoice_on_closed_won",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    # Financial task: ack only after completion and re-queue if the worker is
    # lost mid-run, so a SIGKILL/OOM/redeploy never silently drops the invoice
    # creation. Safe because the task is idempotent (reuses the existing Invoice).
    # NB: the per-task attribute is `reject_on_worker_lost` (the *setting* is
    # `task_reject_on_worker_lost`).
    acks_late=True,
    reject_on_worker_lost=True,
)
def auto_invoice_on_closed_won(self, deal_id: int) -> dict:
    """Triggered after a deal transitions to CLOSED_WON: create the invoice draft + fulfillment.

    Idempotent: safe to run multiple times for the same deal — reuses existing Invoice
    for the contract (if any) and existing Act for the invoice. Needed because:
      * transition_deal_stage may be called twice on a CLOSED_WON→CONTRACT_SIGNED→CLOSED_WON
        reopen loop;
      * Celery task retries duplicate the call.
    """
    from .models import Act, Deal, Invoice
    from .services import ensure_fulfillment, generate_invoice_from_contract, notify_seller_invoice_draft

    try:
        deal = Deal.objects.get(pk=deal_id)
    except Deal.DoesNotExist:
        return {"error": "deal not found"}
    contract = deal.contracts.filter(status__code=ContractStatusCode.SIGNED).order_by("-created_at").first()
    result = {"deal_id": deal_id, "invoice": None, "act": None, "fulfillment": True, "idempotent_reuse": False}
    # Договор передаётся как ПРИВЯЗКА К ВЛАДЕЛЬЦУ: без неё отгрузка уходит в фолбэк видимости
    # и становится видна проигравшему со-роутед продавцу (см. ensure_fulfillment).
    ensure_fulfillment(deal, contract=contract)
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
        # Wave C: the invoice is born a DRAFT (not auto-ISSUED). Nudge the seller team to
        # review + explicitly issue it — the owner keeps control (ERP canon, spec ОВ-2).
        notify_seller_invoice_draft(invoice)
    else:
        result["idempotent_reuse"] = True
    result["invoice"] = invoice.id

    # АКТ ЗДЕСЬ БОЛЬШЕ НЕ ВЫПУСКАЕТСЯ (G1, спека post-contract-open-questions §1).
    #
    # Раньше на этом месте вызывался `generate_act`, и вызов был мёртвым по построению: счёт
    # только что создан в DRAFT, а `generate_act` требует ISSUED/PARTIAL/PAID — то есть акт не
    # выпускался НИКОГДА, только писал предупреждение в лог.
    #
    # Бенчмарк подтвердил, что чинить триггер «в момент выигрыша» и не следовало: закрывающий
    # документ ни в одном эталоне не рождается от подписания сделки. В Odoo он привязан к
    # валидации отгрузки, в SAP приёмку подтверждает ПОЛУЧАТЕЛЬ (принцип двух рук), и оба
    # независимых основания — признание выручки по передаче контроля (IFRS 15 / ASC 606) и
    # правило составления первички по факту хозяйственной жизни — указывают на факт поставки,
    # а не на выигрыш сделки и не на оплату.
    #
    # Теперь акт выпускает продавец кнопкой, а подсказка «сформировать акт» встаёт в цепочке
    # по факту доставки (см. crm/services/deal_documents.py).
    existing_act = (
        Act.objects.filter(invoice=invoice)
        .exclude(status__code=ActStatusCode.CANCELLED)
        .order_by("-created_at")
        .first()
    )
    if existing_act is not None:
        result["act"] = existing_act.id
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
    """Move SENT quotes past `valid_until` to EXPIRED and notify the КП author (prepared_by).

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
    stale_qs = Quote.objects.select_related("status", "prepared_by", "deal").filter(
        status__code="SENT",
        valid_until__isnull=False,
        valid_until__lt=today,
    )
    warn_type = NotificationType.objects.filter(code="WARNING").first()
    from notifications.services import push_notification_ws

    count = 0
    for q in stale_qs:
        q.status = expired_status
        q.save(update_fields=["status", "updated_at"])
        ActivityLog.objects.create(
            action="КП просрочено",
            detail=f"Quote #{q.id} v{q.version} (deal #{q.deal_id}) — valid_until={q.valid_until}",
            user=None,
            level="WARNING",
            deal_id=q.deal_id,
            company_id=q.deal.company_id,
            event_code="quote.expired",
            event_params={
                "quote_id": q.id,
                "version": q.version,
                "deal_id": q.deal_id,
                "valid_until": str(q.valid_until),
            },
        )
        if q.prepared_by and warn_type:
            notif = Notification.objects.create(
                user=q.prepared_by,
                type=warn_type,
                title="КП просрочено",
                message=f"Срок действия КП v{q.version} по сделке #{q.deal_id} истёк",
                link="/crm/quotes",
                deal=q.deal,
                event_code="quote.expired",
                event_params={"version": q.version, "deal_id": q.deal_id},
            )
            push_notification_ws(notif)
        count += 1
    return {"expired": count}


# Render functions by document type. Each takes the model instance and writes its
# `pdf_file`. Kept as a dispatch map so the task and the lazy download fallback share
# one source of truth. The quote uses its lifecycle service (takes an id, not an obj).
def _document_language(doc_type: str, doc_id: int) -> str:
    """Язык печати документа: для закрывающих — язык покупателя, иначе язык платформы.

    КП сюда не попадает намеренно: его язык — дело волны публичной страницы, а не этой.
    Любая ошибка резолва (удалённая строка, гонка) не должна ронять рендер — документ
    важнее языка, поэтому падаем на язык платформы.
    """
    from django.conf import settings

    from .services.document_blocks import document_recipient_language

    getters = {
        "contract": ("Contract", lambda obj: obj.deal),
        "invoice": ("Invoice", lambda obj: obj.deal),
        "act": ("Act", lambda obj: obj.deal),
        "receipt": ("Payment", lambda obj: obj.invoice.deal),
        "delivery_note": ("Fulfillment", lambda obj: obj.deal),
    }
    entry = getters.get(doc_type)
    if entry is None:
        return settings.LANGUAGE_CODE
    model_name, to_deal = entry
    try:
        from django.apps import apps

        obj = apps.get_model("crm", model_name).objects.get(pk=doc_id)
        return document_recipient_language(to_deal(obj))
    except Exception:  # noqa: BLE001 — fault barrier: язык не должен ронять рендер документа
        logger.warning("Could not resolve recipient language for %s id=%s", doc_type, doc_id, exc_info=True)
        return settings.LANGUAGE_CODE


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
    elif doc_type == "receipt":
        from .models import Payment
        from .services.billing import _render_receipt_pdf

        _render_receipt_pdf(Payment.objects.get(pk=doc_id))
    elif doc_type == "delivery_note":
        from .models import Fulfillment
        from .services.fulfillment import _render_delivery_note_pdf

        _render_delivery_note_pdf(Fulfillment.objects.get(pk=doc_id))
    elif doc_type == "quote":
        from .services.quotes import QuoteLifecycleService

        QuoteLifecycleService.generate_pdf(doc_id)
    elif doc_type == "generated":
        from .models import GeneratedDocument
        from .services.generated_documents import _render_generated_pdf

        _render_generated_pdf(GeneratedDocument.objects.get(pk=doc_id))
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
    # M1: закрывающий документ печатается на языке ПОЛУЧАТЕЛЯ. Каркас (лейблы таблиц,
    # итоги, подписи, «сумма прописью») переводится; тело шаблона и формулировки остаются
    # языком автора — канон Stripe: системные лейблы локализуются, custom text нет.
    with translation.override(_document_language(doc_type, doc_id)):
        _render_pdf_for(doc_type, doc_id)
    logger.info("Rendered %s PDF for id=%s", doc_type, doc_id)
    return {"doc_type": doc_type, "doc_id": doc_id, "status": "rendered"}


@shared_task(
    bind=True,
    name="crm.send_quote_email",
    queue="pdf",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_quote_email(self, quote_id: int) -> dict:
    """Email the КП to its recipient on send (off-thread, after commit).

    Unified for both client kinds: a registered buyer (deal.client) and an offline
    contact (deal.contact). Ensures the PDF is rendered first (so it can be attached),
    includes the public no-login link, and is best-effort — a КП is SENT regardless of
    whether the email lands. The seller-only cost projection never leaves the building:
    the attached PDF is the client projection (no margin/charges).
    """
    from notifications.emails import send_templated_email

    from .models import Quote

    quote = Quote.objects.select_related("deal__client", "deal__contact", "deal__company").get(pk=quote_id)

    if not quote.pdf_file:
        _render_pdf_for("quote", quote_id)
        quote.refresh_from_db()

    # Recipient: registered user first, else the offline contact. Resolved by the SHARED service
    # helper that also backs the synchronous RECIPIENT_REQUIRED gate in send_to_client (B5) — the
    # two must never disagree, or a КП gets marked SENT with no email going out. Reaching the
    # `None` branch now means the recipient was removed between the send and this task running.
    from crm.services.quotes import resolve_quote_recipient

    recipient = resolve_quote_recipient(quote)
    if recipient is None:
        logger.warning("Quote %s: no recipient email (client/contact) — email skipped", quote_id)
        return {"quote_id": quote_id, "status": "no_recipient"}
    to_email, to_name = recipient

    attachments = []
    if quote.pdf_file:
        from crm.services.documents import quote_pdf_filename

        try:
            quote.pdf_file.open("rb")
            # Attachment named by the КП number (seller's numbering scheme) — what the client
            # saves must match the document, not an internal deal id (владелец 27-07).
            attachments = [(quote_pdf_filename(quote), quote.pdf_file.read(), "application/pdf")]
        finally:
            quote.pdf_file.close()

    from crm.services.documents import public_quote_url

    public_link = public_quote_url(quote) or ""

    # The КП is prepared by the REAL selling company, never the platform — the email must name it
    # (Rule 1: no hardcoded platform identity). Same resolution as the public page / acceptance code.
    seller_name = getattr(quote.seller_company, "name", None) or "Поставщик"
    # D0 content-correctness: the client sees the КП NUMBER (not the internal deal id) and a sum WITH
    # its currency. `money` is the same NBSP-grouped formatter the PDF uses (reused, not re-invented).
    from crm.templatetags.document_format import money
    from notifications.emails import email_brand

    presentation_ccy = getattr(quote.quote_currency, "code", None) or "UZS"
    quote_number = quote.number or f"{quote.deal_id}-в{quote.version}"
    send_templated_email(
        "quote_sent",
        {
            "recipient_name": to_name,
            "seller_name": seller_name,
            "quote_number": quote_number,
            "quote_version": quote.version,
            "valid_until": quote.valid_until.strftime("%d.%m.%Y") if quote.valid_until else "—",
            "total_incl_vat": money(quote.total_incl_vat, presentation_ccy),
            "public_link": public_link,
            # D1e white-label: the seller's brand opens the email; platform stays in the footer.
            **email_brand(quote.seller_company),
        },
        to=[to_email],
        channel="transactional",
        user=quote.deal.client if quote.deal.client else None,
        attachments=attachments,
        fail_silently=True,
    )
    logger.info("Quote %s email sent to %s", quote_id, to_email)
    return {"quote_id": quote_id, "status": "sent", "to": to_email}


@shared_task(
    bind=True,
    name="crm.send_document_email",
    queue="pdf",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_document_email(self, document_id: int, to_email: str) -> dict:
    """Email an ISSUED generated document to its recipient (off-thread, after commit).

    Ensures the PDF is rendered first (so it can be attached), and includes the public no-login
    link (mirrors send_quote_email). Best-effort — never blocks the request path. The recipient is
    resolved synchronously in the service (send_document_email); this task only trusts that address.
    """
    from notifications.emails import send_templated_email

    from .models import GeneratedDocument
    from .services.generated_documents import public_document_url

    document = GeneratedDocument.objects.select_related("company", "deal", "status").get(pk=document_id)

    # Re-check status at run time (F2-3/MINOR-5): the document may have been CANCELLED between the
    # on_commit enqueue and execution (or on retry) — never mail a cancelled document.
    if document.status_code != "ISSUED":
        return {"document_id": document_id, "status": "skipped_not_issued"}

    if not document.pdf_file:
        _render_pdf_for("generated", document_id)
        document.refresh_from_db()

    attachments = []
    if document.pdf_file:
        try:
            document.pdf_file.open("rb")
            attachments = [(f"Document_{document.number}.pdf", document.pdf_file.read(), "application/pdf")]
        finally:
            document.pdf_file.close()

    from notifications.emails import email_brand

    send_templated_email(
        "generated_document",
        {
            "document_title": document.title or document.number,
            "document_number": document.number,
            "company_name": document.company.name if document.company else "",
            "public_link": public_document_url(document) or "",
            # D1e white-label: the issuing seller's brand opens the email.
            **email_brand(document.company),
        },
        to=[to_email],
        channel="transactional",
        user=None,
        attachments=attachments,
        fail_silently=True,
    )
    logger.info("Generated document %s email sent to %s", document_id, to_email)
    return {"document_id": document_id, "status": "sent", "to": to_email}


@shared_task(
    bind=True,
    name="crm.send_payment_reminders",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_payment_reminders(self, grace_days: int = 3) -> dict:
    """Одно письмо-напоминание по каждому просроченному счёту (G3).

    Просрочка НЕ хранится статусом — она вычисляется здесь из `due_date` и остатка. Эталоны
    поступают так же: у Stripe `past_due` вообще не статус счёта, у Odoo и QuickBooks просрочка
    выводится из срока и оплаты. Хранимый статус пришлось бы синхронизировать, и у Chargebee,
    который его хранит, задокументированы ровно эти рассинхроны.

    Хранится ровно одно — факт отправки (`payment_reminder_sent_at`), иначе ежедневная задача
    слала бы письмо каждый день. Это состояние ПРОЦЕССА напоминаний, как «next reminder date»
    у Odoo, а не статус документа.

    Эскалации пока нет намеренно: эталоны шлют серию, но лишние письма дороже молчания —
    вторую ступень добавим, если первая окажется недостаточной.
    """
    from django.utils import timezone

    from .models import Invoice
    from .services.deal_emails import email_payment_reminder

    cutoff = timezone.now().date() - timedelta(days=grace_days)
    overdue_qs = (
        Invoice.objects.filter(
            due_date__lt=cutoff,
            payment_reminder_sent_at__isnull=True,
            status__code__in=[InvoiceStatusCode.ISSUED, InvoiceStatusCode.PARTIAL],
        )
        .select_related("deal__company", "status")
        .order_by("id")
    )

    reminded = 0
    for invoice in overdue_qs:
        if invoice.balance_due <= 0:
            # Счёт закрыт деньгами, но статус не переключился — напоминать не о чем.
            continue
        if email_payment_reminder(invoice):
            reminded += 1
        # Отмечаем в любом случае: если у покупателя нет ни одного активного адреса, повторная
        # попытка завтра ничего не изменит и превратится в ежедневный холостой проход.
        invoice.payment_reminder_sent_at = timezone.now()
        invoice.save(update_fields=["payment_reminder_sent_at", "updated_at"])
    return {"reminded": reminded}
