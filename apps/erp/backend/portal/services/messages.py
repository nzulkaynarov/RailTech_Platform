"""Чат кабинета (CHAT-1, ADR-0023): лента компании, отправка, прочитанность, присутствие и проекция ответов CRM.

* Компания и автор — только из сессии портала; метка документа (`context`) ищется среди документов компании сессии теми
  же предикатами, что и списки портала (`portal/projections.py`): чужая или невидимая клиенту сделка, КП, счёт или акт —
  `ContextNotFound` (вьюха отвечает 404 без утечки).
* Сообщение контакта и событие `uz.railtech.erp.cabinet.message_posted.v1` — одна транзакция (outbox `rt_bus`). Повтор с
  тем же `client_message_id` в пределах компании — прежнее сообщение, второго события нет. Компания без сопоставления с
  клиентом CRM тоже публикует событие (`crm_client_id: null`) — сообщение не теряется.
* Ответ менеджера (`crm.cabinet.message_sent`) — строка ленты, идемпотентно по `crm_message_id`; ответ, отправленный не
  позже стирания ленты (`crm.lead.erased` с `cabinet_erp_company_id`), не применяется.
* Присутствие (`PortalChatReader.last_seen_at`) обновляет опрос ленты не чаще `PRESENCE_STEP` — по нему NOTIFY-2 решает,
  в кабинете ли контакт.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from parties.models import Company
from portal import projections
from portal.models import PortalChatErasure, PortalChatReader, PortalMessage

from crm.models import Act, Deal, Invoice, Quote

logger = logging.getLogger(__name__)

POSTED_TYPE = "uz.railtech.erp.cabinet.message_posted.v1"
#: Опрос ленты раз в 10 с; присутствие пишется не чаще раза в 30 с (прореживание записей).
PRESENCE_STEP = timedelta(seconds=30)
MAX_PAGE = 100


class ContextNotFound(Exception):
    """Метка документа не принадлежит компании сессии или документ клиенту не виден."""


@dataclass(frozen=True)
class Context:
    kind: str
    id: int
    number: str


def _context_of(company: Company, kind: str, pk: int) -> Context:
    """Документ метки среди видимых клиенту документов компании сессии; иначе `ContextNotFound`."""
    if kind == "deal":
        deal = Deal.objects.filter(company=company, pk=pk).first()
        if deal is not None:
            return Context("deal", deal.pk, projections.deal_number(deal))
    elif kind == "quote":
        quote = Quote.objects.filter(projections.client_quotes_q(), deal__company=company, pk=pk).first()
        if quote is not None:
            return Context("quote", quote.pk, projections.quote_number(quote))
    elif kind == "invoice":
        invoice = Invoice.objects.filter(projections.client_invoices_q(), deal__company=company, pk=pk).first()
        if invoice is not None:
            return Context("invoice", invoice.pk, invoice.number or "")
    elif kind == "act":
        act = Act.objects.filter(projections.client_acts_q(), deal__company=company, pk=pk).first()
        if act is not None:
            return Context("act", act.pk, act.number or "")
    raise ContextNotFound(kind)


def feed(company: Company, *, after_id: Optional[int], limit: int) -> tuple[list[PortalMessage], bool]:
    """Сообщения компании по возрастанию id: после `after_id` или последние `limit`; второе — есть ли ещё."""
    limit = max(1, min(limit, MAX_PAGE))
    rows = PortalMessage.objects.filter(company=company).select_related("author_contact")
    if after_id is not None:
        page = list(rows.filter(id__gt=after_id).order_by("id")[: limit + 1])
        return page[:limit], len(page) > limit
    page = list(rows.order_by("-id")[: limit + 1])
    return list(reversed(page[:limit])), len(page) > limit


def touch_presence(company: Company, contact, now=None) -> None:
    """Контакт смотрит ленту: `last_seen_at`, не чаще `PRESENCE_STEP`."""
    now = now or timezone.now()
    reader, created = PortalChatReader.objects.get_or_create(
        company=company, contact=contact, defaults={"last_seen_at": now}
    )
    if created:
        return
    if reader.last_seen_at is None or now - reader.last_seen_at >= PRESENCE_STEP:
        PortalChatReader.objects.filter(pk=reader.pk).update(last_seen_at=now)


def unread_count(company_id: Optional[int], contact_id: Optional[int]) -> int:
    """Ответы менеджера в ленте компании после отметки «прочитано» контакта."""
    if company_id is None or contact_id is None:
        return 0
    last_read = (
        PortalChatReader.objects.filter(company_id=company_id, contact_id=contact_id)
        .values_list("last_read_id", flat=True)
        .first()
        or 0
    )
    return PortalMessage.objects.filter(
        company_id=company_id, direction=PortalMessage.DIRECTION_MANAGER, id__gt=last_read
    ).count()


def mark_read(company: Company, contact, last_id: int) -> int:
    """Отметка «прочитано до `last_id`» (не уходит назад); `last_id` — сообщение ленты своей компании, иначе
    `PortalMessage.DoesNotExist`. Возвращает число непрочитанных после отметки."""
    if not PortalMessage.objects.filter(company=company, pk=last_id).exists():
        raise PortalMessage.DoesNotExist(last_id)
    with transaction.atomic():
        reader, _ = PortalChatReader.objects.select_for_update().get_or_create(company=company, contact=contact)
        if last_id > reader.last_read_id:
            reader.last_read_id = last_id
            reader.save(update_fields=["last_read_id"])
    return unread_count(company.pk, contact.pk)


def post_message(
    company: Company, contact, *, text: str, client_message_id: str, context: Optional[dict[str, Any]]
) -> tuple[PortalMessage, bool]:
    """Сообщение контакта и событие на шину одной транзакцией; второе — создано ли сейчас (повтор ключа — `False`)."""
    existing = _by_key(company, client_message_id)
    if existing is not None:
        return existing, False
    label = _context_of(company, context["kind"], int(context["id"])) if context else None
    try:
        with transaction.atomic():
            message = PortalMessage.objects.create(
                company=company,
                direction=PortalMessage.DIRECTION_CLIENT,
                author_contact=contact,
                author_name=(contact.name or "")[:255],
                text=text,
                context_kind=label.kind if label else "",
                context_id=label.id if label else None,
                context_number=(label.number if label else "")[:64],
                client_message_id=client_message_id,
            )
            _publish_posted(message, company, contact)
    except IntegrityError:
        # параллельный повтор с тем же ключом успел первым: его строка и есть ответ
        existing = _by_key(company, client_message_id)
        if existing is None:
            raise
        return existing, False
    return message, True


def _by_key(company: Company, client_message_id: str) -> Optional[PortalMessage]:
    return (
        PortalMessage.objects.filter(company=company, client_message_id=client_message_id)
        .select_related("author_contact")
        .first()
    )


def _publish_posted(message: PortalMessage, company: Company, contact) -> None:
    from integration.bus import get_bus
    from integration.models import CrmClientMapping, CrmContactMapping

    crm_client_id = CrmClientMapping.objects.filter(company=company).values_list("crm_client_id", flat=True).first()
    crm_contact_id = CrmContactMapping.objects.filter(contact=contact).values_list("crm_contact_id", flat=True).first()
    payload: dict[str, Any] = {
        "erp_message_id": message.pk,
        "client_message_id": message.client_message_id,
        "author": {"erp_contact_id": contact.pk, "crm_contact_id": crm_contact_id, "name": message.author_name},
        "company_name": (company.name or "")[:255],
        "text": message.text,
        "posted_at": message.created_at.isoformat(),
    }
    if message.context_kind:
        payload["context"] = {
            "kind": message.context_kind,
            "erp_id": message.context_id,
            "number": message.context_number,
        }
    actor: dict[str, Any] = {"type": "client"}
    if message.author_name:
        actor["name"] = message.author_name
    data = {"erp_company_id": company.pk, "crm_client_id": crm_client_id, "actor": actor, "payload": payload}
    get_bus().publish(POSTED_TYPE, data, subject=f"company/{company.pk}", time=message.created_at)


# ── Приём событий CRM ────────────────────────────────────────────────────────────────────────────────────────────────


def apply_manager_reply(data: dict[str, Any]) -> Optional[PortalMessage]:
    """`crm.cabinet.message_sent` → строка ленты (идемпотентно по `crm_message_id`). Компании нет или ответ отправлен
    не позже стирания ленты — `None`."""
    company = Company.objects.filter(pk=data["erp_company_id"]).first()
    if company is None:
        logger.warning("cabinet_reply_unknown_company", extra={"erp_company_id": data["erp_company_id"]})
        return None
    sent_at = parse_datetime(str(data["sent_at"])) or timezone.now()
    erased = PortalChatErasure.objects.filter(company=company).values_list("erased_at", flat=True).first()
    if erased is not None and sent_at <= erased:
        return None
    message, _ = PortalMessage.objects.get_or_create(
        crm_message_id=int(data["message_id"]),
        defaults={
            "company": company,
            "direction": PortalMessage.DIRECTION_MANAGER,
            "author_name": (data.get("manager_name") or "")[:255],
            "text": data["text"],
            "created_at": sent_at,
        },
    )
    return message


def apply_lead_erased(data: dict[str, Any]) -> int:
    """`crm.lead.erased` с `cabinet_erp_company_id`: лента компании до `erased_at` стирается, отметка стирания — чтобы
    опоздавший ответ менеджера её не восстановил. Без поля — ничего (беседы кабинета у лида не было)."""
    company_id = data.get("cabinet_erp_company_id")
    if company_id is None:
        return 0
    erased_at = parse_datetime(str(data["erased_at"])) or timezone.now()
    company = Company.objects.filter(pk=company_id).first()
    if company is None:
        return 0
    deleted, _ = PortalMessage.objects.filter(company=company, created_at__lte=erased_at).delete()
    mark, created = PortalChatErasure.objects.get_or_create(company=company, defaults={"erased_at": erased_at})
    if not created and erased_at > mark.erased_at:
        mark.erased_at = erased_at
        mark.save(update_fields=["erased_at"])
    logger.info("cabinet_chat_erased", extra={"erp_company_id": company.pk, "messages": deleted})
    return deleted
