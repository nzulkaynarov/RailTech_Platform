"""Публикация событий ERP на шину rt_bus из сервисного слоя (B3, ADR-0014, CONTRACTS §3 и §9).

Единственный способ, которым ERP сообщает о своих сущностях: 24 типа `uz.railtech.erp.<сущность>.<действие>.v1`
(`packages/contracts/events/erp/`). Вызывает сервис, который меняет состояние (продажи, документы, портал, интеграция), и
только внутри `transaction.atomic()` этого изменения: `rt_bus` пишет строку outbox в ту же транзакцию, поэтому

- откат изменения — нет события;
- ошибка публикации (в том числе `data` не по схеме типа: проверка строгая, `additionalProperties: false`) — исключение
  наружу и откат изменения. `except Exception` вокруг публикации в ERP нет.

Компания без сопоставления с клиентом CRM (`CrmClientMapping`) событий не порождает — публикатор возвращает `None`;
исключение — `quote.ready_for_approval` (адресат EDS, `crm_client_id: null`).
Корреляция — `X-Request-ID` входящего запроса (`core.logging.RequestIDMiddleware`), вне запроса (Celery) — новый UUID.
Сигналов Django здесь нет: что считать изменением, решает сервис. Событие `document.created` — `document_events.py`.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from django.utils import timezone
from portal import projections
from rt_bus import Event

from ..bus import get_bus
from ..models import CrmClientMapping, CrmContactMapping
from .event_builders import (  # noqa: F401 — публичная поверхность модуля: на неё ссылаются сервисы и тесты
    VALID_EVENT_TYPES,
    _aware,
    _cabinet_url,
    _check_stage,
    build_actor,
    build_deal_ref,
    build_event_data,
    client_actor,
    contact_refs,
    event_type_name,
    request_parties,
)

logger = logging.getLogger(__name__)


def publish_event(
    event_type: str,
    erp_company_id: int,
    payload: Dict[str, Any],
    deal: Optional[Any] = None,
    actor: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[Any] = None,
    crm_client_id: Optional[int] = None,
) -> Optional[Event]:
    """Публикует событие в outbox текущей транзакции; `event_type` — короткое имя (`quote.sent`).

    `None` — компания не сопоставлена клиенту CRM. Вне `transaction.atomic()` — `NotInTransactionError`, `data` не по схеме —
    `EventValidationError` (оба — наружу, изменение откатывается).
    """
    full_type = event_type_name(event_type)
    data = build_event_data(
        erp_company_id=erp_company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        crm_client_id=crm_client_id,
        event_type=full_type,
    )
    if data is None:
        return None
    subject = data["deal"]["number"] if "deal" in data else f"company/{int(erp_company_id)}"
    return get_bus().publish(full_type, data, subject=subject, time=_aware(occurred_at))


# ─────────────────────────────────────────────────────────────────────────────
# Публикаторы по типам событий (CONTRACTS §3)
# ─────────────────────────────────────────────────────────────────────────────

#: Допустимые источники запроса в `request.created` (`RequestCreated.source`).
REQUEST_SOURCES = ("crm", "cabinet", "erp")


def publish_request_created(
    deal: Any,
    source: str = "erp",
    erp_request_id: Optional[int] = None,
    summary: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    crm_client_id: Optional[int] = None,
    manager_crm_user_id: Optional[int] = None,
    letter_file_id: Optional[str] = None,
    crm_request_id: Optional[int] = None,
) -> Optional[Event]:
    """Событие `request.created`: заявка (сделка) создана. Источник решает создатель: портал — `cabinet`, передача из CRM — `crm`.

    Отправитель и менеджер (C1-G-7) — `request_parties`: EDS заполняет ими письмо по заявке. `manager_crm_user_id` —
    менеджер, известный вызывающему (ответственный передачи из CRM); иначе — ответственный сделки ERP.
    «Создать заявку» (W16-D1-2): номер `request_number` (ERP-09) — у каждой сделки с номером ЗВ; заявка процесса `v3`
    несёт `process` и `urgency`; файл письма `letter_file_id` и заявка CRM `crm_request_id` — если их дал вызывающий.
    """
    if source not in REQUEST_SOURCES:
        source = "erp"
    company_id = deal.company_id if hasattr(deal, "company_id") else deal["company_id"]
    if not company_id:
        return None  # сделка без компании (черновик калькулятора) клиенту CRM не принадлежит
    payload: Dict[str, Any] = {"source": source}
    if erp_request_id is not None:
        payload["erp_request_id"] = erp_request_id
    if summary:
        payload["summary"] = summary
    if not isinstance(deal, dict):
        payload.update(request_parties(deal, manager_crm_user_id))
        payload.update(_request_details(deal))
    if letter_file_id:
        payload["letter_file_id"] = str(letter_file_id)
    if crm_request_id:
        payload["crm_request_id"] = int(crm_request_id)

    return publish_event(
        "request.created",
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        crm_client_id=crm_client_id,
    )


def _request_details(deal: Any) -> Dict[str, Any]:
    """Номер ЗВ, процесс и срочность заявки для `request.created` (W16-D1-2)."""
    details: Dict[str, Any] = {}
    number = getattr(deal, "number", "") or ""
    if number.startswith("ЗВ-"):
        details["request_number"] = number
    if getattr(deal, "process", "") == "v3":
        details["process"] = "v3"
        details["urgency"] = getattr(deal, "urgency", "") or "normal"
    return details


def publish_deal_stage_changed(
    deal: Any,
    from_stage: str,
    to_stage: str,
    reason: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
) -> Optional[Event]:
    """Событие `deal.stage_changed`."""
    company_id = deal.company_id if hasattr(deal, "company_id") else deal["company_id"]
    if not company_id:
        return None
    payload: Dict[str, Any] = {
        "from": _check_stage(from_stage),
        "to": _check_stage(to_stage),
    }
    if reason:
        payload["reason"] = reason

    return publish_event("deal.stage_changed", erp_company_id=company_id, payload=payload, deal=deal, actor=actor)


def publish_deal_outcome(
    deal: Any,
    won: bool,
    amount: Optional[Union[str, Decimal]] = None,
    currency: Optional[str] = None,
    lost_reason: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
) -> Optional[Event]:
    """События `deal.won` / `deal.lost`."""
    company_id = deal.company_id if hasattr(deal, "company_id") else deal["company_id"]
    if not company_id:
        return None
    ref = build_deal_ref(deal)
    if amount is None:
        # Итог сделки несёт сумму всегда (`DealOutcome.amount` обязателен): отправленное клиенту КП, иначе ноль.
        amount = ref["amount"] or "0.00"
    amount = f"{Decimal(str(amount)):.2f}"

    currency = (currency or ref["currency"]).upper()

    payload: Dict[str, Any] = {"amount": amount, "currency": currency}
    if not won and lost_reason:
        payload["lost_reason"] = lost_reason

    return publish_event(
        "deal.won" if won else "deal.lost",
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
    )


def publish_quote_sent(
    quote: Any,
    public_url: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    channels: Optional[list[str]] = None,
) -> Optional[Event]:
    """Событие `quote.sent`. `channels` — каналы автоотправки после одобрения директором (ERP-11): CRM пишет клиенту в
    Telegram, только если там есть `telegram`; нет списка — отправка менеджером, все каналы клиента (как прежде)."""
    deal = quote.deal
    company_id = deal.company_id

    if not public_url:
        # Публичная страница КП — одна функция на ERP (письмо клиенту, PDF, портал); домен — из настроек.
        from crm.services.documents.public_page import public_quote_url

        # Токена ещё нет (КП в статусе «отправлено» без публичной ссылки) — карточка КП в Cabinet по сессии клиента.
        public_url = public_quote_url(quote) or f"{_cabinet_url()}/quotes/{quote.id}"

    total_amount = f"{quote.total_incl_vat:.2f}"
    currency = projections.currency_code(quote.quote_currency)

    valid_until_str = None
    if getattr(quote, "valid_until", None):
        valid_until_str = quote.valid_until.isoformat()

    payload: Dict[str, Any] = {
        "erp_quote_id": quote.id,
        "version": quote.version,
        "public_url": public_url,
        "valid_until": valid_until_str,
        "total": total_amount,
        "currency": currency.upper(),
    }
    if channels is not None:
        payload["channels"] = list(dict.fromkeys(channels))

    return publish_event("quote.sent", erp_company_id=company_id, payload=payload, deal=deal, actor=actor)


def publish_quote_outcome(
    event_type: str,
    quote: Any,
    reason: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    contact: Optional[Any] = None,
) -> Optional[Event]:
    """События `quote.viewed`, `quote.accepted`, `quote.rejected`.

    `contact` — контакт клиента, принявший или отклонивший КП в Cabinet (Q-FIX22-6): в `payload` уходят `erp_contact_id`
    и `crm_contact_id` (`null`, если контакт не сопоставлен), действующее лицо — клиент с именем контакта. Без контакта
    (публичная страница КП, менеджер) полей нет.
    """
    if event_type not in ("quote.viewed", "quote.accepted", "quote.rejected"):
        raise ValueError(f"Не итог КП: {event_type!r}")
    deal = quote.deal
    company_id = deal.company_id
    payload: Dict[str, Any] = {
        "erp_quote_id": quote.id,
        "version": quote.version,
    }
    if reason:
        payload["reason"] = reason
    if contact is not None:
        payload.update(contact_refs(contact))
        if actor is None:
            actor = client_actor(contact)

    return publish_event(event_type, erp_company_id=company_id, payload=payload, deal=deal, actor=actor)


def publish_quote_ready_for_approval(
    quote: Any, payload: Dict[str, Any], actor: Optional[Dict[str, Any]] = None
) -> Event:
    """Событие `quote.ready_for_approval` (EDS-03): КП готово к одобрению директором, EDS открывает маршрут «КП».

    Адресат — EDS (и BFF как подсказка); в отличие от событий для CRM публикуется и для компании без клиента CRM
    (`crm_client_id: null`). `payload` собирает `crm/services/eds_quote_approval.py`; `subject` — номер КП.
    """
    deal = quote.deal
    crm_client_id = (
        CrmClientMapping.objects.filter(company_id=deal.company_id).values_list("crm_client_id", flat=True).first()
    )
    data: Dict[str, Any] = {
        "erp_company_id": int(deal.company_id),
        "crm_client_id": crm_client_id,
        "deal": build_deal_ref(deal),
        "actor": actor or {"type": "system"},
        "payload": payload,
    }
    return get_bus().publish(event_type_name("quote.ready_for_approval"), data, subject=payload["number"])


def publish_quote_acceptance_code_requested(quote: Any, contact: Any, code: str, expires_at: Any) -> Optional[Event]:
    """Событие `quote.acceptance_code_requested`: клиент запросил код акцепта в Cabinet, код доставит бот CRM (Q-FIX22-1).

    Шлётся только контакту, сопоставленному с контактом CRM (`crm_contact_id`): иначе боту некому писать — `None`, и
    вызывающий код отправляет код письмом. `code` — секрет: в outbox он попадает маской `***`, значение лежит в кэше
    (`DjangoCacheStash`, 20 минут) и подставляется только в тело доставки; в логи не пишется.
    """
    crm_contact_id = CrmContactMapping.objects.filter(contact=contact).values_list("crm_contact_id", flat=True).first()
    if not crm_contact_id:
        return None
    deal = quote.deal
    return publish_event(
        "quote.acceptance_code_requested",
        erp_company_id=deal.company_id,
        payload={
            "erp_quote_id": quote.id,
            "version": quote.version,
            "erp_contact_id": contact.id,
            "crm_contact_id": crm_contact_id,
            "code": code,
            "expires_at": expires_at.isoformat(),
        },
        deal=deal,
        actor=client_actor(contact),
    )


def publish_contract_signed(contract: Any, by: str = "both", actor: Optional[Dict[str, Any]] = None) -> Optional[Event]:
    """Событие `contract.signed`: `by` — `client`, `company` или `both`."""
    deal = contract.deal
    payload: Dict[str, Any] = {
        "erp_contract_id": contract.id,
        "number": contract.number or f"CT-{contract.id}",
        "by": by,
    }
    return publish_event("contract.signed", erp_company_id=deal.company_id, payload=payload, deal=deal, actor=actor)


def publish_invoice_event(
    event_type: str,
    invoice: Any,
    link: Optional[str] = None,
    erp_document_id: Optional[int] = None,
    actor: Optional[Dict[str, Any]] = None,
) -> Optional[Event]:
    """События `invoice.issued`, `invoice.paid`, `invoice.overdue`."""
    if event_type not in ("invoice.issued", "invoice.paid", "invoice.overdue"):
        raise ValueError(f"Не событие счёта: {event_type!r}")
    deal = invoice.deal
    company_id = deal.company_id

    currency = "UZS"
    if getattr(invoice, "currency", None):
        c = invoice.currency
        currency = c.code if hasattr(c, "code") else str(c)

    due_date_str = invoice.due_date.isoformat() if invoice.due_date else timezone.localdate().isoformat()
    if not link:
        link = f"{_cabinet_url()}/invoices/{invoice.id}"

    payload: Dict[str, Any] = {
        "erp_invoice_id": invoice.id,
        "number": invoice.number or f"INV-{invoice.id}",
        "amount": f"{invoice.total_incl_vat:.2f}",
        "currency": currency.upper(),
        "due_date": due_date_str,
        "link": link,
    }
    if erp_document_id:
        payload["erp_document_id"] = erp_document_id

    return publish_event(event_type, erp_company_id=company_id, payload=payload, deal=deal, actor=actor)


#: Статусы исполнения сделки в `DeliveryEvent.status` контракта. Принято и оспорено клиентом — физически «доставлено»:
#: решения клиента идут отдельными событиями `delivery.line_accepted|disputed` (FIX-62, Q-FIX62-1).
_DELIVERY_STATUS_MAP = {"accepted": "delivered", "disputed": "delivered"}
_DELIVERY_STATUSES = ("assembling", "in_transit", "ready_to_ship", "shipped", "delivered")


def publish_delivery_event(
    event_type: str,
    fulfillment: Any,
    line_summary: str = "Строки поставки",
    line_nos: Optional[List[int]] = None,
    previous_eta: Optional[Any] = None,
    actor: Optional[Dict[str, Any]] = None,
) -> Optional[Event]:
    """События `delivery.status_changed`, `delivery.eta_changed`."""
    if event_type not in ("delivery.status_changed", "delivery.eta_changed"):
        raise ValueError(f"Не событие исполнения: {event_type!r}")
    deal = fulfillment.deal
    company_id = deal.company_id

    status_str = "assembling"
    if getattr(fulfillment, "status", None):
        status_val = fulfillment.status.code if hasattr(fulfillment.status, "code") else str(fulfillment.status)
        status_str = status_val.lower()

    status_str = _DELIVERY_STATUS_MAP.get(status_str, status_str)
    if status_str not in _DELIVERY_STATUSES:
        status_str = "assembling"

    eta_str = None
    if getattr(fulfillment, "expected_delivery_date", None):
        eta_str = fulfillment.expected_delivery_date.isoformat()

    prev_eta_str = None
    if previous_eta:
        prev_eta_str = previous_eta.isoformat() if hasattr(previous_eta, "isoformat") else str(previous_eta)

    payload: Dict[str, Any] = {
        "line_summary": line_summary,
        "status": status_str,
        "eta": eta_str,
        "tracking": getattr(fulfillment, "tracking_number", "") or None,
    }
    if line_nos:
        payload["line_nos"] = line_nos
    if prev_eta_str:
        payload["previous_eta"] = prev_eta_str

    return publish_event(event_type, erp_company_id=company_id, payload=payload, deal=deal, actor=actor)


def publish_act_event(
    event_type: str,
    act: Any,
    reason: Optional[str] = None,
    erp_document_id: Optional[int] = None,
    actor: Optional[Dict[str, Any]] = None,
) -> Optional[Event]:
    """События `act.issued`, `act.accepted`, `act.returned`."""
    if event_type not in ("act.issued", "act.accepted", "act.returned"):
        raise ValueError(f"Не событие акта: {event_type!r}")
    deal = act.deal
    payload: Dict[str, Any] = {
        "erp_act_id": act.id,
        "number": act.number or f"ACT-{act.id}",
    }
    if reason:
        payload["reason"] = reason
    if erp_document_id:
        payload["erp_document_id"] = erp_document_id

    return publish_event(event_type, erp_company_id=deal.company_id, payload=payload, deal=deal, actor=actor)


def publish_invite_sent(contact: Any, channels: List[str], actor: Optional[Dict[str, Any]] = None) -> Optional[Event]:
    """Событие `invite.sent`."""
    company_id = contact.company_id
    if not company_id:
        return None

    crm_contact_id = CrmContactMapping.objects.filter(contact=contact).values_list("crm_contact_id", flat=True).first()

    clean_channels = [c for c in channels if c in ("telegram", "email")]
    if not clean_channels:
        clean_channels = ["email"]

    payload: Dict[str, Any] = {
        "channels": clean_channels,
        "erp_contact_id": contact.id,
    }
    if crm_contact_id:
        payload["crm_contact_id"] = crm_contact_id

    return publish_event("invite.sent", erp_company_id=company_id, payload=payload, deal=None, actor=actor)


def publish_invite_requested(contact: Any, actor: Optional[Dict[str, Any]] = None) -> Optional[Event]:
    """Событие `invite.requested` (D1-9): приглашение в Cabinet через Telegram — доставит бот CRM, ERP в Telegram не пишет.

    Шлётся только контакту, сопоставленному с контактом CRM (`crm_contact_id`) и с привязанным `telegram_user_id`:
    иначе боту некому писать — `None`, и вызывающий код отвечает `CONTACT_TELEGRAM_REQUIRED`. В событии нет ссылки
    входа и токенов: контакт открывает Mini App, а сессию выпускает подписанный `initData` его аккаунта.
    """
    if not contact.company_id or not contact.telegram_user_id:
        return None
    crm_contact_id = CrmContactMapping.objects.filter(contact=contact).values_list("crm_contact_id", flat=True).first()
    if not crm_contact_id:
        return None
    payload: Dict[str, Any] = {"channel": "telegram", "erp_contact_id": contact.id, "crm_contact_id": crm_contact_id}
    if contact.language in ("ru", "uz", "en"):
        payload["language"] = contact.language
    return publish_event("invite.requested", erp_company_id=contact.company_id, payload=payload, deal=None, actor=actor)


#: Решение клиента по строке поставки → тип события (`DeliveryLineDecision.status`).
DELIVERY_LINE_EVENTS = {"accepted": "delivery.line_accepted", "disputed": "delivery.line_disputed"}

#: `DeliveryLineDecision.remark.maxLength`.
DELIVERY_LINE_REMARK_MAX = 2000


def publish_delivery_line_decision(line: Any, contact: Any) -> Optional[Event]:
    """События `delivery.line_accepted` / `delivery.line_disputed`: клиент принял или оспорил строку поставки (FIX-37).

    Решение уже записано в `line` (`status` — `accepted`/`disputed`, `accepted_at` — время решения, `remark` — замечание).
    Событие пишется в outbox транзакции решения: откат решения — нет события, ошибка публикации — решение откатывается.
    Действующее лицо — клиент с именем контакта.
    """
    status = str(line.status)
    event_type = DELIVERY_LINE_EVENTS.get(status)
    if event_type is None:
        raise ValueError(f"Строка поставки в статусе {status!r} не даёт события приёмки/замечания")
    deal = line.deal
    decided_at = line.accepted_at or timezone.now()
    payload: Dict[str, Any] = {
        "line_no": line.line_no,
        "title": line.title or f"Строка {line.line_no}",
        "status": status,
        "decided_at": decided_at.isoformat(),
    }
    if status == "disputed":
        payload["remark"] = (line.remark or "").strip()[:DELIVERY_LINE_REMARK_MAX]

    return publish_event(
        event_type,
        erp_company_id=deal.company_id,
        payload=payload,
        deal=deal,
        actor=client_actor(contact),
        occurred_at=decided_at,
    )
