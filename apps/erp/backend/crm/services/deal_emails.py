"""Транзакционные письма пути «после контракта» (G3).

До этой волны на отрезке счёт → оплата → закрывающий документ не было НИ ОДНОГО письма —
только уведомления внутри приложения. Это ровно тот случай, когда in-app недостаточно:
покупатель здесь часто внешний контрагент, который в систему может и не зайти, а
«in-app физически не достаёт отсутствующего пользователя».

Почему писем ровно четыре. Бенчмарк (Stripe, Odoo, Xero, QuickBooks, PandaDoc, DocuSign,
Bill.com) сходится на минимуме: счёт выставлен, оплата получена, напоминание о просрочке,
документ ждёт ответа второй стороны. Всё остальное — создание черновика, смены статуса,
доставку, приёмку — эталоны оставляют внутри системы. Это не экономия ради экономии:
репутация домена считается целиком, и жалобы на малоценные письма бьют по доставке
критичных (порог Google/Yahoo — 0,3% жалоб, ориентир 0,1%).

Обвязка одна на все письма: по ОДНОЙ задаче на получателя (компании-конкуренты не должны
видеть адреса друг друга) и только `on_commit` — письмо не должно пережить откат транзакции.
Мёртвый брокер не имеет права свалить бизнес-операцию, ради которой письмо отправляли.
"""

import logging

from django.conf import settings
from django.db import transaction

from notifications.text_format import text_money

logger = logging.getLogger(__name__)


def _invoice_url(invoice) -> str:
    return f"{settings.FRONTEND_URL}/#invoices?open={invoice.pk}"


def _currency_code(invoice) -> str:
    """Код валюты счёта; у счёта без валюты — базовая (`text_money` подставит её сам)."""
    return invoice.currency.code if invoice.currency_id else ""


def _emails_for(user_ids) -> list:
    from accounts.models import CustomUser

    return list(
        CustomUser.objects.filter(pk__in=list(user_ids), is_active=True).exclude(email="").values_list("email", "pk")
    )


def send_deal_email(template: str, context: dict, user_ids, *, deal) -> int:
    """Поставить письмо сотрудникам в очередь после коммита. Возвращает число адресатов.

    `deal` обязателен (ТЕСТ-2): по записи тестовой компании письмо получают только сотрудники с включённым «Показывать
    тестовые»; письма клиенту (Кабинет, `document_letters`) идут другим путём и не затрагиваются."""
    from notifications.gate import staff_recipients

    recipients = _emails_for(staff_recipients(user_ids, deal))
    if not recipients:
        return 0

    def _enqueue():
        from notifications.tasks import send_transactional_email

        for email, user_id in recipients:
            try:
                send_transactional_email.delay(template, context, to=[email], channel="transactional", user_id=user_id)
            except Exception:  # noqa: BLE001 — недоступный брокер не должен ронять операцию
                logger.exception("%s email enqueue failed for %s", template, email)

    transaction.on_commit(_enqueue)
    return len(recipients)


def email_invoice_issued(invoice) -> int:
    """Контактам сделки: счёт выставлен и его ждут к оплате (ДК-3).

    Письмо с PDF и личной ссылкой получателя в Кабинет (`document_letters`), а не прежним участникам компании в ERP.
    Черновик письма НЕ порождает — только выставление.
    """
    from .document_letters import email_document

    return email_document("invoice", invoice)


def email_payment_received(payment) -> int:
    """Продавцу: деньги пришли. У Stripe квитанция об оплате включена по умолчанию; у нас
    продавец до этого не узнавал об оплате, не зайдя в систему."""
    from .deal_notifications import seller_team_user_ids

    invoice = payment.invoice
    deal = invoice.deal
    context = {
        "invoice_number": invoice.number,
        "deal_title": deal.title or "",
        "buyer_name": deal.company.name if deal.company_id else "",
        "amount": text_money(payment.amount, _currency_code(invoice)),
        "paid_total": text_money(invoice.amount_paid, _currency_code(invoice)),
        "total": text_money(invoice.total_incl_vat, _currency_code(invoice)),
        "is_fully_paid": invoice.amount_paid >= invoice.total_incl_vat,
        "invoice_url": _invoice_url(invoice),
    }
    return send_deal_email("payment_received", context, seller_team_user_ids(deal), deal=deal)


def email_payment_reminder(invoice) -> int:
    """Контактам сделки: срок оплаты прошёл (ДК-3).

    Единственное событие отрезка, где эталоны шлют не одно письмо, а серию (Odoo +15/+30/+40,
    Xero +7/+14/+21). Начинаем с ОДНОГО напоминания — эскалацию добавлять, только если она
    понадобится: лишние письма дороже молчания. Ссылка в письме — новая, на того же получателя.
    """
    from .document_letters import email_document

    return email_document("invoice", invoice, reminder=True)


def email_act_awaiting_acceptance(act) -> int:
    """Контактам сделки: акт выставлен и ждёт ответа — принять или вернуть с причиной (ДК-3).

    Аналог «invitation to sign» у PandaDoc/DocuSign: письмо с PDF и личной ссылкой получателя; решение — в Кабинете
    по коду из письма.
    """
    from .document_letters import email_document

    return email_document("act", act)
