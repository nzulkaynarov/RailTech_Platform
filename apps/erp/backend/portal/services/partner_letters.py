"""Письмо партнёру с запросом цены или заказом поставщику (ДК-5, ADR-0030): PDF и одна кнопка на личную ссылку контакта.

Письмо — это уведомление ленты кабинета (`partner_rfq_sent`, `partner_order_sent`): очередь, повторы, «письмо дошло или
нет» остаются у `portal.services.notices`; здесь только содержимое. Ссылка выпускается именно этому контакту (адрес и
документ записаны в ней, из запроса не берутся), живёт до срока документа плюс месяц и отзывается сотрудником в карточке
запроса или заказа. Письмо, которое не передано почте, гасит свою ссылку: у получателя её нет, повтор выпустит новую.
Та же ссылка уходит в бот, если у контакта привязан Telegram (ДК-4); сбой бота письмо не отменяет.
"""

from __future__ import annotations

import logging
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

#: Уведомление ленты → вид документа ссылки.
KIND_BY_NOTICE = {"partner_order_sent": "supplier_order", "partner_rfq_sent": "price_request"}


def document_of(notice):
    """Документ партнёра, о котором уведомление; нет документа или он больше партнёру не виден — `None`."""
    from portal.services.doc_link_kinds import spec_of
    from supply.models import PriceRequest, SupplierOrder

    kind = KIND_BY_NOTICE[notice.kind]
    model = SupplierOrder if kind == "supplier_order" else PriceRequest
    doc = model.objects.select_related("supplier").filter(pk=notice.object_id, supplier_id=notice.company_id).first()
    if doc is None or not spec_of(kind).visible(doc):
        return None
    return doc


def send_letter(notice) -> Optional[object]:
    """Отправить письмо по уведомлению: журнал письма или `None` — документа уже нет (письмо не нужно)."""
    from portal.services import doc_links
    from portal.services.doc_link_kinds import spec_of

    from crm.templatetags.document_format import money
    from notifications.emails import email_brand, send_templated_email
    from notifications.models import EmailLog
    from notifications.text_format import text_date

    doc = document_of(notice)
    if doc is None:
        return None
    kind = KIND_BY_NOTICE[notice.kind]
    spec = spec_of(kind)
    contact = notice.contact
    attachments = []
    try:
        pdf = spec.pdf_bytes(doc)
        if pdf:
            attachments = [(f"{spec.number(doc) or doc.pk}.pdf".replace("/", "-"), pdf, "application/pdf")]
    except Exception:  # noqa: BLE001 — письмо со ссылкой важнее вложения: PDF откроется и по ссылке
        logger.exception("%s #%s: PDF was not built for the letter", kind, doc.pk)
    link, raw = doc_links.mint_document_link(kind, doc, contact.email, contact.name)
    if link.contact_id != contact.pk:  # два контакта с одним адресом: ссылка — тому, кому адресовано уведомление
        link.contact = contact
        link.save(update_fields=["contact"])
    code = spec.currency_code(doc)
    context = {
        "kind": kind,
        "recipient_name": contact.name,
        "buyer_name": spec.seller_name(doc),
        "number": spec.number(doc),
        "total": money(spec.total(doc), code) if kind == "supplier_order" else "",
        "expected_date": text_date(getattr(doc, "expected_date", None)),
        "public_link": doc_links.build_url(raw),
        **email_brand(doc_links._seller_company(link)),
    }
    log = send_templated_email(
        "partner_document_sent",
        context,
        to=[contact.email.strip().lower()],
        language=contact.language,
        purpose=f"portal_notice.{notice.kind}",
        attachments=attachments,
        fail_silently=True,
    )
    if log is not None and log.status == EmailLog.STATUS_FAILED:
        link.revoked_at = timezone.now()  # письмо не ушло: ссылка, которой нет у получателя, живой не остаётся
        link.save(update_fields=["revoked_at"])
        return log
    try:
        doc_links.send_link_telegram(link, raw)
    except Exception:  # noqa: BLE001 — письмо уже передано: сбой бота его не отменяет и не повторяет
        logger.exception("%s #%s: telegram link event failed", kind, doc.pk)
    return log
