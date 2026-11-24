"""Письмо с документом по ссылке получателя (ДК-3, ADR-0030): договор, счёт, акт — как КП.

Одно письмо на получателя: PDF во вложении и одна кнопка на личную ссылку в Кабинете (`/d/<токен>`), выпущенную именно
ему. Получатели — контакты сделки и те, кому уже уходили документы сделки (`doc_links.deal_recipients`), а не прежние
участники компании в ERP. Письмо уходит после коммита, по одной задаче на получателя (адреса друг другу не видны), и не
может уронить операцию, ради которой отправлено: сбой почты — в лог, документ остаётся выданным.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def email_document(kind: str, doc, *, reminder: bool = False) -> int:
    """Поставить письма с документом в очередь после коммита; возвращает число получателей."""
    from portal.services import doc_links
    from portal.services.doc_link_kinds import spec_of

    recipients = doc_links.deal_recipients(spec_of(kind).deal(doc))
    if not recipients:
        return 0
    doc_id = doc.pk

    def _enqueue():
        from crm.tasks import send_document_link_email

        for email, name in recipients:
            try:
                send_document_link_email.delay(kind, doc_id, email, name, reminder)
            except Exception:  # noqa: BLE001 — недоступный брокер не должен ронять операцию
                logger.exception("%s #%s: document letter was not enqueued for %s", kind, doc_id, email)

    transaction.on_commit(_enqueue)
    return len(recipients)


def deliver_document_letter(kind: str, doc_id: int, email: str, name: str, reminder: bool = False) -> dict:
    """Выпустить ссылку получателя и отправить письмо с PDF; вызывается задачей `crm.send_document_link_email`."""
    from portal.services import doc_links
    from portal.services.doc_link_kinds import spec_of

    from crm.templatetags.document_format import money
    from notifications.emails import email_brand, send_templated_email
    from notifications.models import EmailLog

    spec = spec_of(kind)
    doc = _load(kind, doc_id)
    if doc is None or not spec.visible(doc):
        return {"kind": kind, "id": doc_id, "status": "skipped_not_visible"}

    if not spec.pdf_file(doc):
        from crm.tasks import _render_pdf_for

        _render_pdf_for(kind, doc_id)
        doc = _load(kind, doc_id)
    attachments = []
    pdf = spec.pdf_file(doc) or doc.pdf_file
    if pdf:
        try:
            pdf.open("rb")
            attachments = [(_pdf_name(kind, doc), pdf.read(), "application/pdf")]
        finally:
            pdf.close()

    link, raw = doc_links.mint_document_link(kind, doc, email, name)
    code = spec.currency_code(doc)
    context = {
        "kind": kind,
        "reminder": reminder,
        "recipient_name": name,
        "seller_name": spec.seller_name(doc),
        "number": spec.number(doc),
        "total": money(spec.total(doc), code),
        "public_link": doc_links.build_url(raw),
        **_facts(kind, doc, code, money),
        **email_brand(doc_links._seller_company(link)),
    }
    log = send_templated_email(
        "document_link_sent",
        context,
        to=[email.strip().lower()],
        channel="transactional",
        language=link.contact.language if link.contact is not None else None,
        attachments=attachments,
        fail_silently=True,
    )
    if getattr(log, "status", "") == EmailLog.STATUS_FAILED:
        # письмо не передано почте: ссылка, которой нет у получателя, не остаётся живой (повторная отправка выпустит новую)
        link.revoked_at = timezone.now()
        link.save(update_fields=["revoked_at"])
        return {"kind": kind, "id": doc_id, "status": "failed", "to": email}
    return {"kind": kind, "id": doc_id, "status": "sent", "to": email}


def _facts(kind: str, doc, code: str, money) -> dict:
    if kind != "invoice":
        return {}
    from portal import projections

    due = projections.invoice_due_date(doc)
    return {
        "due_date": due.strftime("%d.%m.%Y") if due else "",
        "balance_due": money(doc.balance_due, code),
    }


def _load(kind: str, doc_id: int):
    from crm.models import Act, Contract, Invoice

    model = {"contract": Contract, "invoice": Invoice, "act": Act}[kind]
    return model.objects.select_related("deal__company", "deal__contact", "deal__client").filter(pk=doc_id).first()


def _pdf_name(kind: str, doc) -> str:
    number = (doc.number or str(doc.pk)).replace("/", "-")
    return f"{number}.pdf"
