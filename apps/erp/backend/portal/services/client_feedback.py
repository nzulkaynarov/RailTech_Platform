"""«Я оплатил» и комментарий к КП из кабинета клиента (B-CABFIX-1; SPEC-v3 §3.1 шаг 8, §8; контракт `erp-portal.yaml`).

Платёжка клиента — та же `PaymentConfirmation`, что прикладывает менеджер (`finance.services.receivables.attach_confirmation`),
с источником `CABINET`: она сразу видна в «Счета и оплаты» → «Платёжки на подтверждение» Платформы и ждёт, пока менеджер
сверит поступление с выпиской и подтвердит оплату (`confirm_payment`). Деньгами платёжка не считается.

Комментарий к КП — `portal.QuoteComment`; клиент пишет, пока КП ждёт решения. Оба действия — запись в `ActivityLog`
сделки (с `company`) и уведомление ответственному по сделке, как замечание по поставке (`sales.services.delivery_lines`).
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional

from django.db import transaction
from finance.models import Invoice, PaymentConfirmation
from finance.services.receivables import OPEN_STATUSES
from portal.exceptions import PortalConflict
from portal.models import QuoteComment
from portal.projections import quote_number
from portal.services.act_scan import load_scan

from crm.models import ActivityLog

#: Событие журнала то же, что у платёжки, приложенной менеджером: история счёта в Платформе показывает обе.
PROOF_LOG_EVENT = "payment_doc.attached"
#: Коды уведомлений (центр уведомлений ERP → колокольчик Платформы, вкладка «Решения»).
PROOF_NOTIFY_EVENT = "payment.proof_received"
COMMENT_EVENT = "quote.client_commented"


def responsible_ids(deal) -> list[int]:
    """Кому уходит действие клиента: ответственный по сделке, иначе продающие сотрудники своей компании."""
    from crm.services.deal_notifications import seller_team_user_ids

    for holder in (deal.assigned_to_id, deal.manager_id):
        if holder:
            return [holder]
    return seller_team_user_ids(deal)


def submit_payment_proof(
    invoice: Invoice,
    contact,
    *,
    upload_id: str,
    paid_on: Optional[datetime.date],
    amount: Optional[Decimal],
    comment: str,
) -> PaymentConfirmation:
    """Платёжное поручение клиента к счёту его компании: счёт уже найден по компании сессии (чужой — 404 во view).

    Оплаченный или отменённый счёт — 409 `INVOICE_NOT_OPEN` (как у `attach_confirmation`); файл — из `POST /uploads`
    этой компании, PDF или изображение не больше лимита (`load_scan`: иначе 422 `UPLOAD_NOT_FOUND` / `VALIDATION_ERROR`).
    """
    with transaction.atomic():
        locked = Invoice.objects.select_for_update(of=("self",)).select_related("deal", "status").get(pk=invoice.pk)
        if locked.status_code not in OPEN_STATUSES:
            raise PortalConflict("INVOICE_NOT_OPEN")
        upload, content = load_scan(locked.deal.company, upload_id, locked.deal)
        confirmation = PaymentConfirmation.objects.create(
            invoice=locked,
            source=PaymentConfirmation.Source.CABINET,
            file=content,
            original_name=upload.name[:255],
            claimed_amount=amount,
            claimed_date=paid_on,
            note=comment.strip(),
        )
        upload.deal = locked.deal
        upload.save(update_fields=["deal"])
        ActivityLog.objects.create(
            action="Клиент приложил платёжку",
            detail=f"Счёт {locked.number}: платёжное поручение из кабинета клиента",
            event_code=PROOF_LOG_EVENT,
            event_params={
                "number": locked.number,
                "confirmation_id": confirmation.pk,
                "source": PaymentConfirmation.Source.CABINET,
                "contact_id": contact.pk,
            },
            level="INFO",
            deal=locked.deal,
            company_id=locked.deal.company_id,
            entity_type="invoice",
            entity_id=locked.pk,
        )
        transaction.on_commit(lambda: _notify_proof(locked, confirmation))
    return confirmation


def _notify_proof(invoice: Invoice, confirmation: PaymentConfirmation) -> None:
    from crm.services.deal_notifications import notify_deal_users
    from notifications.services import spa_link

    notify_deal_users(
        responsible_ids(invoice.deal),
        deal=invoice.deal,
        title=f"Клиент приложил платёжку по счёту {invoice.number}",
        message=(
            f"Счёт {invoice.number}: платёжное поручение из кабинета клиента. "
            "Сверьте поступление с выпиской банка и подтвердите оплату в «Счетах и оплатах»."
        ),
        link=spa_link("invoices", invoice.pk),
        type_code="INFO",
        event_code=PROOF_NOTIFY_EVENT,
        event_params={"number": invoice.number, "confirmation_id": confirmation.pk},
    )


def add_quote_comment(quote, contact, text: str) -> QuoteComment:
    """Комментарий клиента к КП, которое ждёт решения (проверка статуса — во view, как у отклонения)."""
    clean = text.strip()
    number = quote_number(quote)
    with transaction.atomic():
        comment = QuoteComment.objects.create(quote=quote, author_contact=contact, text=clean)
        ActivityLog.objects.create(
            action="Клиент прокомментировал КП",
            detail=f"КП {number} (версия {quote.version}): {clean}",
            event_code=COMMENT_EVENT,
            event_params={"number": number, "version": quote.version, "contact_id": contact.pk, "note": clean},
            level="INFO",
            deal=quote.deal,
            company_id=quote.deal.company_id,
            entity_type="quote",
            entity_id=quote.pk,
        )
        transaction.on_commit(lambda: _notify_comment(quote, number, clean))
    return comment


def _notify_comment(quote, number: str, text: str) -> None:
    from crm.services.deal_notifications import notify_deal_users
    from notifications.services import spa_link

    notify_deal_users(
        responsible_ids(quote.deal),
        deal=quote.deal,
        title=f"Комментарий клиента к КП {number}",
        message=text[:500],
        link=spa_link("quotes", quote.pk),
        type_code="INFO",
        event_code=COMMENT_EVENT,
        event_params={"number": number, "version": quote.version},
    )
