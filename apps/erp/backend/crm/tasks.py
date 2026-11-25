"""Celery tasks for the CRM app."""

import logging
from datetime import timedelta

from celery import shared_task
from celery.exceptions import Retry, SoftTimeLimitExceeded
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone, translation

from core.currency import BASE_CURRENCY
from notifications.text_format import deal_ref

from .constants import ActStatusCode, ContractStatusCode, FulfillmentStatusCode, InvoiceStatusCode

logger = logging.getLogger(__name__)


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

    today = timezone.localdate()
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

    today = timezone.localdate()
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
                message=f"Срок действия КП v{q.version} по сделке {deal_ref(q.deal)} истёк",
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
# Вид документа → (приложение, модель, путь к сделке). Модели живут в `sales` и `finance`, а не в `crm`: раньше поиск шёл
# по `crm` и для каждого вида молча падал в язык платформы с предупреждением (FIX-55, m2 D-6).
_DOCUMENT_LANGUAGE_MODELS = {
    "contract": ("sales", "Contract", lambda obj: obj.deal),
    "invoice": ("finance", "Invoice", lambda obj: obj.deal),
    "act": ("finance", "Act", lambda obj: obj.deal),
    "receipt": ("finance", "Payment", lambda obj: obj.invoice.deal),
    "delivery_note": ("sales", "Fulfillment", lambda obj: obj.deal),
}


def _document_language(doc_type: str, doc_id: int) -> str:
    """Язык печати документа: для закрывающих — язык покупателя, иначе язык платформы.

    КП сюда не попадает намеренно: его язык — дело волны публичной страницы, а не этой.
    Любая ошибка резолва (удалённая строка, гонка) не должна ронять рендер — документ
    важнее языка, поэтому падаем на язык платформы.
    """
    from django.conf import settings

    from .services.document_blocks import document_recipient_language

    entry = _DOCUMENT_LANGUAGE_MODELS.get(doc_type)
    if entry is None:
        return settings.LANGUAGE_CODE
    app_label, model_name, to_deal = entry
    try:
        from django.apps import apps

        obj = apps.get_model(app_label, model_name).objects.get(pk=doc_id)
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
    name="crm.send_document_link_email",
    queue="pdf",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_document_link_email(self, kind: str, doc_id: int, email: str, name: str = "", reminder: bool = False) -> dict:
    """ДК-3: письмо с договором, счётом или актом получателю — PDF и личная ссылка в Кабинет (`document_letters`)."""
    from .services.document_letters import deliver_document_letter

    return deliver_document_letter(kind, doc_id, email, name, reminder)


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

    # ДК-1: письмо ведёт в Кабинет — своя ссылка на получателя (`/d/<токен>`, в базе только хеш). Не получилось выпустить
    # (нет получателя уже отсечено выше) — прежняя страница ERP, КП всё равно уходит.
    minted = None
    try:
        from portal.services.doc_links import build_url, mint_quote_link

        _link, raw_link_token = mint_quote_link(quote)
        public_link = build_url(raw_link_token)
        minted = (_link, raw_link_token)
    except Exception:  # noqa: BLE001 — письмо с КП важнее ссылки: падаем назад на страницу ERP, ошибку не прячем
        logger.exception("Quote %s: document link was not minted, falling back to the ERP page", quote_id)
        public_link = public_quote_url(quote) or ""

    # The КП is prepared by the REAL selling company, never the platform — the email must name it
    # (Rule 1: no hardcoded platform identity). Same resolution as the public page / acceptance code.
    seller_name = getattr(quote.seller_company, "name", None) or "Поставщик"
    # D0 content-correctness: the client sees the КП NUMBER (not the internal deal id) and a sum WITH
    # its currency. `money` is the same NBSP-grouped formatter the PDF uses (reused, not re-invented).
    from crm.templatetags.document_format import money
    from notifications.emails import email_brand

    presentation_ccy = getattr(quote.quote_currency, "code", None) or BASE_CURRENCY
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
        # W18A-P1: письмо уходит через почтовый сервис CRM; итог (отправлено / ошибка) вернётся событием и попадёт в
        # журнал КП и `Quote.send_report` (`notifications/mail_bus.py`).
        ref=("quote", quote.pk),
    )
    logger.info("Quote %s email handed to the CRM mail service for %s", quote_id, to_email)
    if minted is not None:
        # ДК-4: та же личная ссылка — в бот, если у получателя привязан Telegram (письмо остаётся основным каналом).
        from portal.services.doc_links import send_link_telegram

        try:  # письмо уже передано: сбой бота не должен повторить задачу и второй раз отправить письмо
            send_link_telegram(*minted)
        except Exception:  # noqa: BLE001
            logger.exception("Quote %s: telegram link event failed", quote_id)
    return {"quote_id": quote_id, "status": "sent", "to": to_email}


@shared_task(name="crm.render_document_sample", queue="pdf", time_limit=120, soft_time_limit=100)
def render_document_sample(sample_id: str, company_id: int, user_id: int, request: dict) -> dict:
    """Render the sample document of the settings screens (ДОК-14) off the request thread.

    The same generator as a working document, on a sample context; the PDF is kept in the cache for the screen. Never
    retried: the screen asks again after the next edit.
    """
    from .services.documents.sample import run_sample

    run_sample(sample_id, company_id, user_id, request)
    return {"sample_id": sample_id}


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

    from crm.services.pdf_storage import safe_file_name

    attachments = []
    if document.pdf_file:
        try:
            document.pdf_file.open("rb")
            attachments = [
                (safe_file_name(f"Document_{document.number}.pdf"), document.pdf_file.read(), "application/pdf")
            ]
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
        ref=("document", document.pk),
    )
    logger.info("Generated document %s email handed to the CRM mail service for %s", document_id, to_email)
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

    cutoff = timezone.localdate() - timedelta(days=grace_days)
    overdue_qs = (
        Invoice.objects.filter(
            due_date__lt=cutoff,
            payment_reminder_sent_at__isnull=True,
            status__code__in=[InvoiceStatusCode.ISSUED, InvoiceStatusCode.PARTIAL],
        )
        .select_related("deal__company", "status")
        .order_by("id")
    )

    reminded = failed = 0
    for invoice in overdue_qs:
        if not reminders_enabled(invoice):
            # Напоминания включает компания-продавец в Настройках (по умолчанию выключено — DECISIONS 2026-11-04):
            # счёт не отмечается, событие не публикуется — после включения напоминание уйдёт.
            continue
        if invoice.balance_due <= 0:
            # Счёт закрыт деньгами, но статус не переключился — напоминать не о чем.
            continue
        try:
            _remind_overdue_invoice(invoice)
        except Exception:  # noqa: BLE001 — сбой одного счёта (шина, БД) не останавливает остальные; итог задачи — ниже
            failed += 1
            logger.exception("send_payment_reminders: счёт #%s не обработан, отметка и событие откатены", invoice.pk)
            continue
        reminded += 1
    if failed:
        # Не молча: задача завершается ошибкой (повтор по backoff подберёт необработанные — отмеченные счета не затрагиваются).
        raise RuntimeError(f"send_payment_reminders: не обработано счетов — {failed}, обработано — {reminded}")
    return {"reminded": reminded}


def reminders_enabled(invoice) -> bool:
    """Продавец счёта (нет — своя компания) включил «Напоминать клиентам о просроченных счетах» (NOTIFY-2)."""
    from core.tenant import own_company

    from .services.billing import _invoice_seller_company

    seller = _invoice_seller_company(invoice) or own_company()
    return bool(seller is not None and seller.settings.remind_overdue_invoices)


def _remind_overdue_invoice(invoice) -> None:
    """Один просроченный счёт: отметка «напоминание отправлено» + событие шины `invoice.overdue` — в одной транзакции.

    Событие рождается на отметке: ровно одно на просроченный счёт (статуса «просрочен» нет, его вычисляет задача). Письмо
    покупателю уходит только после коммита (`on_commit`): откатилась отметка или публикация — письма нет. Отмечаем и тогда,
    когда у покупателя нет ни одного активного адреса: повтор завтра ничего не изменит.
    """
    from django.utils import timezone
    from integration.services import events

    from .services.deal_emails import email_payment_reminder

    with transaction.atomic():
        invoice.payment_reminder_sent_at = timezone.now()
        invoice.save(update_fields=["payment_reminder_sent_at", "updated_at"])
        events.publish_invoice_event("invoice.overdue", invoice)
        transaction.on_commit(lambda: email_payment_reminder(invoice), robust=True)


@shared_task(
    bind=True,
    name="crm.run_contract_terms",
    time_limit=600,
    soft_time_limit=540,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def run_contract_terms(self) -> dict:
    """ДС-1: ежедневно — продлить договоры «сам», напомнить о последнем дне отказа; повтор в тот же день ничего не меняет."""
    from .services import contract_term

    return contract_term.run_daily()


# --- Файл письма клиента заявки без резолюции (РЕЗ-1) ---
LETTER_FILE_MAX_RETRIES = 5
#: Сеть и хранилище не должны держать воркер: мягкий предел — запись в журнал, жёсткий — подстраховка.
LETTER_FILE_SOFT_TIME_LIMIT = 60
LETTER_FILE_TIME_LIMIT = 90


def _finish(deal_id: int, *, attached: bool, reason: str = "") -> None:
    """Расчёт больше не ждёт файл — пришёл он или нет. Не пришёл — запись в журнале заявки (заявки нет — писать некуда)."""
    from sales.models import CalcTask, Deal

    from crm.services import calc_tasks

    CalcTask.objects.filter(deal_id=deal_id, eds_letter_id__isnull=True).update(request_file_pending=False)
    if attached:
        return
    deal = Deal.objects.filter(pk=deal_id).first()
    if deal is None:
        return
    calc_tasks.deal_log(
        deal,
        "Файл письма клиента не получен",
        f"Файл основания заявки не удалось взять в расчёт ({reason}); откройте письмо клиента вручную",
        event_code="deal.request_file_missing",
        event_params={"reason": reason},
        level="WARNING",
    )


def enqueue_request_letter_file(deal_id: int, file_id: str, created_by: int) -> None:
    """Поставить задачу после коммита. Не поставилась (брокер недоступен) — расчёт не ждёт файл вечно: флаг снят, запись в
    журнале заявки."""
    try:
        fetch_request_letter_file.delay(deal_id, file_id, created_by)
    except Exception:  # noqa: BLE001 — любой сбой постановки: брокер, сериализация
        logger.exception("fetch_request_letter_file: not enqueued, deal %s", deal_id)
        _finish(deal_id, attached=False, reason="queue_unavailable")


@shared_task(
    bind=True,
    name="crm.fetch_request_letter_file",
    max_retries=LETTER_FILE_MAX_RETRIES,
    soft_time_limit=LETTER_FILE_SOFT_TIME_LIMIT,
    time_limit=LETTER_FILE_TIME_LIMIT,
)
def fetch_request_letter_file(self, deal_id: int, file_id: str, created_by: int) -> bool:
    """Файл письма клиента → исходники заявки (`deal_request_files`). Идемпотентно: тот же файл второй раз не кладётся.

    Любой окончательный сбой — EDS не отдаёт файл, хранилище не приняло, заявка исчезла, вышло время — снимает «файл
    загружается» и пишет в журнал заявки; расчёт не остаётся в ожидании."""
    from sales.models import Deal

    from sourcing.models import Attachment, AttachmentKind

    from integration.services import eds_files

    try:
        if not Deal.objects.filter(pk=deal_id).exists():
            _finish(deal_id, attached=False, reason="deal_gone")
            return False
        try:
            found = eds_files.fetch_request_file(file_id, created_by)
        except eds_files.EdsFileUnavailable as exc:
            if self.request.retries >= LETTER_FILE_MAX_RETRIES:
                _finish(deal_id, attached=False, reason="eds_unavailable")
                return False
            raise self.retry(exc=exc, countdown=min(30 * 2**self.request.retries, 900))
        if found is None:
            _finish(deal_id, attached=False, reason="not_found")
            return False
        name, data = found
        already = Attachment.objects.filter(
            deal_id=deal_id, kind=AttachmentKind.SOURCE, original_filename=name
        ).exists()
        if not already:
            Attachment.objects.create(
                deal_id=deal_id, kind=AttachmentKind.SOURCE, original_filename=name, file=ContentFile(data, name=name)
            )
    except Retry:
        raise
    except SoftTimeLimitExceeded:
        _finish(deal_id, attached=False, reason="timeout")
        return False
    except Exception:  # noqa: BLE001 — хранилище, база: окончательный сбой, не оставляем расчёт в ожидании
        logger.exception("fetch_request_letter_file: failed, deal %s", deal_id)
        _finish(deal_id, attached=False, reason="storage_error")
        return False
    _finish(deal_id, attached=True)
    return True
