"""Письмо не дошло (отказ почты): тому, кто его отправил, — строка в «Решениях» с причиной и адресом.

Итог доставки приходит от CRM (`crm.mail.failed`, `mail_bus.apply_mail_result`; CRM узнаёт об отказе из
отчётов о недоставке, `app/services/bounces.py`). КП обрабатывает `mail_bus._apply_quote_result`; здесь —
остальные письма с адресатом-сотрудником: договор, счёт, акт, приглашение в кабинет, заказ поставщику.
Отправитель определяется по объекту письма (`ref`), его в ERP хранят сами документы: автор КП договора,
менеджер сделки счёта и акта, `sent_by` заказа, инициатор приглашения. Нет отправителя — никому: письмо
остаётся в журнале писем, а штат не засыпается чужим отказом.
"""

import logging
from typing import Any, Optional
from urllib.parse import quote as url_quote

logger = logging.getLogger(__name__)

#: Виды `ref`, которые обрабатываются здесь; ключ — код события колокольчика.
EVENT_BY_KIND = {
    "contract": "contract.email_failed",
    "invoice": "invoice.email_failed",
    "act": "act.email_failed",
    "invitation": "invitation.email_failed",
    "supplier_order": "supplier_order.email_failed",
}
TITLES = {
    "contract": "Письмо с договором {name} не доставлено",
    "invoice": "Письмо со счётом {name} не доставлено",
    "act": "Письмо с актом {name} не доставлено",
    "invitation": "Приглашение в кабинет не доставлено: {name}",
    "supplier_order": "Заказ поставщику {name} не доставлен",
}


def notify_sender(kind: str, ref_id: str, to: list[str], reason: str) -> bool:
    """Строка в колокольчик отправителю; `True` — отправитель найден и уведомлён."""
    resolver = _RESOLVERS.get(kind)
    if resolver is None:
        return False
    found = resolver(ref_id)
    if found is None:
        logger.info("mail failure for %s %s has no sender to tell", kind, ref_id)
        return False
    sender, name, link, deal = found
    if sender is None:
        return False
    from notifications.services import notify_user

    address = ", ".join(to)
    notify_user(
        user=sender,
        title=TITLES[kind].format(name=name)[:200],
        message=f"{address}: {reason}. Проверьте адрес и отправьте снова.",
        link=link,
        deal=deal,
        type_code="WARNING",
        event_code=EVENT_BY_KIND[kind],
        event_params={"number": name, "to": address, "reason": reason, "kind": kind},
    )
    return True


Found = Optional[tuple[Any, str, str, Any]]  # (отправитель, как назвать, ссылка, сделка)


def _project_link(deal) -> str:
    return f"/eds/projects/{url_quote(deal.number or f'D-{deal.pk}', safe='')}"


def _document(model_name: str):
    def resolve(ref_id: str) -> Found:
        from crm import models as crm_models

        if not ref_id.isdigit():
            return None
        doc = (
            getattr(crm_models, model_name)
            .objects.select_related("deal__manager", "deal__assigned_to")
            .filter(pk=int(ref_id))
            .first()
        )
        if doc is None:
            return None
        deal = doc.deal
        quote = getattr(doc, "quote", None)
        author = getattr(quote, "prepared_by", None) if quote is not None else None
        sender = author or deal.manager or deal.assigned_to
        return sender, (doc.number or f"#{doc.pk}"), _project_link(deal), deal

    return resolve


def _invitation(ref_id: str) -> Found:
    """`ref_id` = `<id контакта>:<id сотрудника, отправившего>`; сотрудника нет — менеджер последней сделки компании."""
    from parties.models import Contact

    from accounts.models import CustomUser

    contact_part, _, actor_part = ref_id.partition(":")
    if not contact_part.isdigit():
        return None
    contact = Contact.objects.select_related("company").filter(pk=int(contact_part)).first()
    if contact is None:
        return None
    sender = CustomUser.objects.filter(pk=int(actor_part)).first() if actor_part.isdigit() else None
    if sender is None:
        from crm.models import Deal

        deal = (
            Deal.objects.filter(company_id=contact.company_id)
            .select_related("manager", "assigned_to")
            .order_by("-created_at", "-id")
            .first()
        )
        sender = (deal.manager or deal.assigned_to) if deal is not None else None
    return sender, (contact.name or contact.email or f"#{contact.pk}"), "/company", None


def _supplier_order(ref_id: str) -> Found:
    from supply.models import SupplierOrder

    if not ref_id.isdigit():
        return None
    order = SupplierOrder.objects.select_related("sent_by").filter(pk=int(ref_id)).first()
    if order is None:
        return None
    return order.sent_by, order.number, f"/erp/stock/{url_quote(order.number, safe='')}", None


_RESOLVERS = {
    "contract": _document("Contract"),
    "invoice": _document("Invoice"),
    "act": _document("Act"),
    "invitation": _invitation,
    "supplier_order": _supplier_order,
}
