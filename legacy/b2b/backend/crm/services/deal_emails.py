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

logger = logging.getLogger(__name__)


def _deal_url(deal) -> str:
    return f"{settings.FRONTEND_URL}/#request-detail/{deal.pk}"


def _invoice_url(invoice) -> str:
    return f"{settings.FRONTEND_URL}/#invoices?open={invoice.pk}"


def _emails_for(user_ids) -> list:
    from accounts.models import CustomUser

    return list(
        CustomUser.objects.filter(pk__in=list(user_ids), is_active=True).exclude(email="").values_list("email", "pk")
    )


def send_deal_email(template: str, context: dict, user_ids) -> int:
    """Поставить письмо в очередь каждому получателю после коммита. Возвращает число адресатов."""
    recipients = _emails_for(user_ids)
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
    """Покупателю: счёт выставлен и его ждут к оплате.

    Обязательный минимум у всех эталонов. Черновик письма НЕ порождает — только выставление.
    """
    from .deal_notifications import buyer_team_user_ids

    deal = invoice.deal
    context = {
        "invoice_number": invoice.number,
        "deal_title": deal.title or "",
        "seller_name": _seller_name(invoice),
        "total": str(invoice.total_incl_vat),
        "due_date": invoice.due_date.isoformat() if invoice.due_date else "",
        "invoice_url": _invoice_url(invoice),
    }
    return send_deal_email("invoice_issued", context, buyer_team_user_ids(deal))


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
        "amount": str(payment.amount),
        "paid_total": str(invoice.amount_paid),
        "total": str(invoice.total_incl_vat),
        "is_fully_paid": invoice.amount_paid >= invoice.total_incl_vat,
        "invoice_url": _invoice_url(invoice),
    }
    return send_deal_email("payment_received", context, seller_team_user_ids(deal))


def email_payment_reminder(invoice) -> int:
    """Покупателю: срок оплаты прошёл.

    Единственное событие отрезка, где эталоны шлют не одно письмо, а серию (Odoo +15/+30/+40,
    Xero +7/+14/+21). Начинаем с ОДНОГО напоминания — эскалацию добавлять, только если она
    понадобится: лишние письма дороже молчания.
    """
    from .deal_notifications import buyer_team_user_ids

    deal = invoice.deal
    context = {
        "invoice_number": invoice.number,
        "deal_title": deal.title or "",
        "seller_name": _seller_name(invoice),
        "total": str(invoice.total_incl_vat),
        "balance_due": str(invoice.balance_due),
        "due_date": invoice.due_date.isoformat() if invoice.due_date else "",
        "invoice_url": _invoice_url(invoice),
    }
    return send_deal_email("payment_reminder", context, buyer_team_user_ids(deal))


def email_act_awaiting_acceptance(act) -> int:
    """Заказчику: акт выставлен и ждёт его ответа — принять или вернуть с причиной.

    Аналог «invitation to sign» у PandaDoc/DocuSign. Реестр актов покупателю закрыт, поэтому
    ведём на карточку сделки, где акт виден в блоке цепочки.
    """
    from .deal_notifications import buyer_team_user_ids

    deal = act.deal
    context = {
        "act_number": act.number,
        "deal_title": deal.title or "",
        "total": str(act.total_amount),
        "deal_url": _deal_url(deal),
    }
    return send_deal_email("act_awaiting_acceptance", context, buyer_team_user_ids(deal))


def _seller_name(invoice) -> str:
    """Имя продавца для письма — то же, что печатается в самом счёте (Rule 1/2: никогда не
    подставляем платформу вместо реального поставщика)."""
    from .billing import _invoice_seller_company

    supplier = _invoice_seller_company(invoice)
    return supplier.name if supplier else ""
