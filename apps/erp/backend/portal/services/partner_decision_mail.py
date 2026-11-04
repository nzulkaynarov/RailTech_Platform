"""Письмо партнёру о решении по карточке (PART-3): «опубликована» или «возвращена: причина», ссылка — в «Мои товары».

Получатели — активные контакты компании-источника карточки с правом действовать (`can_act`) и адресом, если партнёру
открыт кабинет с модулем «Мои товары»: письмо со ссылкой в закрытый кабинет бесполезно. Язык письма — по контакту, Reply-To —
сотрудник, принявший решение. Письмо уходит после фиксации решения; сбой почты решение не откатывает (запись `EmailLog`
со статусом FAILED остаётся). Когда появится маршрутизатор уведомлений кабинета (ADR-0023, NOTIFY-2), отправка перейдёт на него.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from parties.models import Contact, active_contact_q
from portal.services.access import company_access
from portal.services.mail_context import responsible_manager_email

from catalog.models.reviews import ISSUE_FIELDS
from notifications.emails import send_templated_email

logger = logging.getLogger(__name__)

MODULE = "my_products"
PUBLISHED_TEMPLATE = "partner_card_published"
RETURNED_TEMPLATE = "partner_card_returned"

#: Подписи полей замечаний в письме (на языке контакта); перечень полей — `catalog.models.reviews.ISSUE_FIELDS`.
ISSUE_LABELS = {
    "name": _("Наименование"),
    "description": _("Описание"),
    "brand": _("Бренд"),
    "manufacturer_part_number": _("Артикул изготовителя"),
    "gost_drawing": _("ГОСТ / чертёж"),
    "category": _("Категория"),
    "uom": _("Единица измерения"),
    "hs_code": _("Код ТН ВЭД"),
    "price": _("Цена"),
    "valid_until": _("Цена действует до"),
    "other": _("Другое"),
}
assert set(ISSUE_LABELS) == set(ISSUE_FIELDS)  # новое поле замечания без подписи письма не проходит импорт


def card_url(product_id: int) -> str:
    return f"{getattr(settings, 'CABINET_URL', 'http://cabinet.localhost').rstrip('/')}/my-products?card={product_id}"


def recipients(company) -> list[Contact]:
    """Контакты партнёра, которым писать о решении: с правом действовать, с адресом, при открытом «Мои товары»."""
    _roles, modules = company_access(company.pk)
    if MODULE not in modules:
        return []
    return list(
        Contact.objects.filter(active_contact_q(), company=company, can_act=True).exclude(email="").order_by("id")
    )


def notify_decision(product, decision: str, *, reason: str = "", issues=(), actor=None) -> int:
    """Письма контактам партнёра о решении `published` / `returned`; сколько писем передано (0 — писать некому)."""
    company = product.source_supplier
    if company is None or decision not in ("published", "returned"):
        return 0
    template = PUBLISHED_TEMPLATE if decision == "published" else RETURNED_TEMPLATE
    reply_to = responsible_manager_email(company.pk, actor)
    sent = 0
    for contact in recipients(company):
        context = {
            "contact_name": contact.name,
            "company_name": company.name,
            "product_name": product.name,
            "card_url": card_url(product.pk),
        }
        if decision == "returned":
            context["reason"] = reason
            context["issues"] = [{"label": ISSUE_LABELS[item["field"]], "comment": item["comment"]} for item in issues]
        try:
            send_templated_email(
                template,
                context=context,
                to=[contact.email.strip().lower()],
                channel="transactional",
                language=contact.language,
                reply_to=[reply_to] if reply_to else None,
                fail_silently=True,
            )
            sent += 1
        except Exception:  # noqa: BLE001 — решение уже принято; письмо не должно его ломать
            logger.exception("Partner decision mail failed: product=%s contact=%s", product.pk, contact.pk)
    return sent
