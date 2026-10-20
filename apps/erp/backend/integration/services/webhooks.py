"""Webhook dispatch service for ERP -> CRM events (CONTRACTS §3, M3-ERP-02).

Спецификация вебхуков: POST {CRM}/api/v1/integrations/erp/events.
Заголовки:
- X-Event-Id (UUIDv4)
- X-Event-Type
- X-Timestamp (ISO-8601 with tz)
- X-Signature: sha256=<HMAC(body, ERP_WEBHOOK_SECRET)>

Тело и валидация соответствуют JSON-схеме `packages/contracts/events.schema.json`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import CrmClientMapping, CrmContactMapping, IntegrationWebhookEvent, WebhookEventStatus
from . import stages

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = {
    "request.created",
    "deal.stage_changed",
    "quote.sent",
    "quote.viewed",
    "quote.accepted",
    "quote.rejected",
    "contract.signed",
    "invoice.issued",
    "invoice.paid",
    "invoice.overdue",
    "delivery.status_changed",
    "delivery.eta_changed",
    "act.issued",
    "act.accepted",
    "act.returned",
    "deal.won",
    "deal.lost",
    "document.created",
    "invite.sent",
    "delivery.line_accepted",
    "delivery.line_disputed",
}


def sign_payload(secret: str, body_bytes: bytes) -> str:
    """Вычисляет HMAC-SHA256 подпись тела запроса в формате sha256=<hex>."""
    signature = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


def verify_signature(secret: str, body_bytes: bytes, signature_header: str) -> bool:
    """Проверяет заголовок X-Signature."""
    expected = sign_payload(secret, body_bytes)
    return hmac.compare_digest(expected, signature_header.strip())


def _format_amount(value: Optional[Union[str, Decimal]]) -> Optional[str]:
    """Контракт `Amount`: строка с двумя знаками; `None` — суммы нет."""
    return None if value is None else f"{Decimal(str(value)):.2f}"


def _check_stage(stage: Any) -> str:
    """Стадия в событии — только код `DealStage` контракта; всё остальное — ошибка вызывающего кода."""
    if not stages.is_deal_stage(stage):
        raise ValueError(f"Стадия {stage!r} не из контракта шва (DealStage): {', '.join(stages.DEAL_STAGES)}")
    return stage


def build_deal_ref(deal: Any) -> Dict[str, Any]:
    """Формирует объект DealRef для тела события по events.schema.json.

    Стадия и сумма — из `stages.py`, как в ответах integration: сумма — последняя версия КП, видимая клиенту,
    иначе `null` (черновики в сумму сделки не входят). Словарь на входе — уже готовая проекция (`stage` — код
    `DealStage`, `amount` — строка либо `None`).
    """
    if isinstance(deal, dict):
        erp_deal_id = int(deal["erp_deal_id"])
        return {
            "erp_deal_id": erp_deal_id,
            "number": str(deal.get("number") or f"D-{erp_deal_id}"),
            "title": str(deal.get("title") or f"Сделка #{erp_deal_id}"),
            "stage": _check_stage(deal.get("stage")),
            "amount": _format_amount(deal.get("amount")),
            "currency": str(deal.get("currency", "UZS")).upper(),
        }

    # Django Deal Model
    erp_deal_id = deal.id
    return {
        "erp_deal_id": erp_deal_id,
        "number": f"D-{erp_deal_id}",
        "title": deal.title or f"Сделка #{erp_deal_id}",
        "stage": stages.deal_stage(deal),
        "amount": _format_amount(stages.deal_amount(deal)),
        "currency": stages.deal_currency(deal),
    }


def build_actor(
    user: Optional[Any] = None,
    actor_type: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Формирует объект Actor по events.schema.json."""
    if actor_type is None:
        if user is None:
            actor_type = "system"
        elif getattr(user, "is_portal_user", False):
            actor_type = "client"
        else:
            actor_type = "staff"

    if actor_type not in ("system", "staff", "client"):
        actor_type = "system"

    actor: Dict[str, Any] = {"type": actor_type}
    if name:
        actor["name"] = name
    elif user:
        user_name = ""
        if hasattr(user, "get_full_name"):
            user_name = user.get_full_name()
        if not user_name:
            user_name = getattr(user, "name", "") or getattr(user, "username", "")
        if user_name:
            actor["name"] = user_name

    return actor


def build_event_envelope(
    event_type: str,
    erp_company_id: int,
    payload: Dict[str, Any],
    deal: Optional[Any] = None,
    actor: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[Any] = None,
    crm_client_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Собирает полный JSON-объект события по schema.

    Если компания не связана с CRM (нет CrmClientMapping) и crm_client_id не передан явно,
    отправка вебхука пропускается (возвращает None), т.к. CRM принимает только привязанные события.
    """
    if crm_client_id is None:
        mapping = CrmClientMapping.objects.filter(company_id=erp_company_id).first()
        if not mapping:
            logger.info(
                "Skipping webhook event %s for unmapped company #%s",
                event_type,
                erp_company_id,
            )
            return None
        crm_client_id = mapping.crm_client_id

    if occurred_at is None:
        occurred_at = timezone.now()
    if hasattr(occurred_at, "isoformat"):
        if timezone.is_naive(occurred_at):
            occurred_at = timezone.make_aware(occurred_at)
        occurred_at_str = occurred_at.isoformat()
    else:
        occurred_at_str = str(occurred_at)

    envelope: Dict[str, Any] = {
        "version": 1,
        "event": event_type,
        "occurred_at": occurred_at_str,
        "erp_company_id": int(erp_company_id),
        "crm_client_id": int(crm_client_id),
        "actor": actor or {"type": "system"},
        "payload": payload,
    }

    if deal is not None:
        envelope["deal"] = build_deal_ref(deal)

    return envelope


def emit_event(
    event_type: str,
    erp_company_id: int,
    payload: Dict[str, Any],
    deal: Optional[Any] = None,
    actor: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[Any] = None,
    crm_client_id: Optional[int] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """Создает запись исходящего вебхука и ставит задачу доставки в Celery.

    Если компания не сопоставлена клиенту CRM, событие не создается и возвращается None.
    Нет секрета подписи — событие всё равно записывается (PENDING, без `X-Signature`): подписывает задача
    доставки в момент отправки, и пока секрета нет, событие ждёт, а не теряется (FIX-33).
    """
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("Attempted to emit unsupported event type: %s", event_type)
    secret = settings.ERP_WEBHOOK_SECRET
    if not secret:
        logger.error("ERP_WEBHOOK_SECRET is not configured — event %s is kept PENDING unsigned", event_type)

    envelope = build_event_envelope(
        event_type=event_type,
        erp_company_id=erp_company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        occurred_at=occurred_at,
        crm_client_id=crm_client_id,
    )
    if not envelope:
        return None

    event_id = uuid.uuid4()
    webhook_url = settings.CRM_WEBHOOK_URL

    body_bytes = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Event-Id": str(event_id),
        "X-Event-Type": event_type,
        "X-Timestamp": envelope["occurred_at"],
    }
    if secret:
        headers["X-Signature"] = sign_payload(secret, body_bytes)

    event_obj = IntegrationWebhookEvent.objects.create(
        event_id=event_id,
        event_type=event_type,
        target_url=webhook_url,
        payload=envelope,
        headers=headers,
        status=WebhookEventStatus.PENDING,
    )

    def _queue_task():
        from ..tasks import deliver_webhook_event

        deliver_webhook_event.delay(event_obj.id)

    if send_async:
        transaction.on_commit(_queue_task)

    return event_obj


# ─────────────────────────────────────────────────────────────────────────────
# Специфические генераторы событий (CONTRACTS §3)
# ─────────────────────────────────────────────────────────────────────────────


def emit_request_created(
    deal: Any,
    source: str = "erp",
    erp_request_id: Optional[int] = None,
    summary: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
    crm_client_id: Optional[int] = None,
) -> Optional[IntegrationWebhookEvent]:
    """Событие request.created."""
    company_id = deal.company_id if hasattr(deal, "company_id") else deal["company_id"]
    payload: Dict[str, Any] = {"source": source}
    if erp_request_id is not None:
        payload["erp_request_id"] = erp_request_id
    if summary:
        payload["summary"] = summary

    return emit_event(
        event_type="request.created",
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
        crm_client_id=crm_client_id,
    )


def emit_deal_stage_changed(
    deal: Any,
    from_stage: str,
    to_stage: str,
    reason: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """Событие deal.stage_changed."""
    company_id = deal.company_id if hasattr(deal, "company_id") else deal["company_id"]
    payload: Dict[str, Any] = {
        "from": _check_stage(from_stage),
        "to": _check_stage(to_stage),
    }
    if reason:
        payload["reason"] = reason

    return emit_event(
        event_type="deal.stage_changed",
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_deal_outcome(
    deal: Any,
    won: bool,
    amount: Optional[Union[str, Decimal]] = None,
    currency: Optional[str] = None,
    lost_reason: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """События deal.won / deal.lost."""
    company_id = deal.company_id if hasattr(deal, "company_id") else deal["company_id"]
    ref = build_deal_ref(deal)
    if amount is None:
        # Итог сделки несёт сумму всегда (`DealOutcome.amount` обязателен): отправленное клиенту КП, иначе ноль.
        amount = ref["amount"] or "0.00"
    amount = f"{Decimal(str(amount)):.2f}"

    currency = (currency or ref["currency"]).upper()

    payload: Dict[str, Any] = {"amount": amount, "currency": currency}
    if not won and lost_reason:
        payload["lost_reason"] = lost_reason

    event_type = "deal.won" if won else "deal.lost"
    return emit_event(
        event_type=event_type,
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_quote_sent(
    quote: Any,
    public_url: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """Событие quote.sent."""
    deal = quote.deal
    company_id = deal.company_id

    if not public_url:
        token = getattr(quote, "public_token", None) or f"q-{quote.id}"
        public_url = f"https://cabinet.railtech.uz/q/{token}"

    total_amount = f"{quote.total_incl_vat:.2f}"
    currency = "UZS"
    if getattr(quote, "currency", None):
        c = quote.currency
        currency = c.code if hasattr(c, "code") else str(c)

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

    return emit_event(
        event_type="quote.sent",
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_quote_outcome(
    event_type: str,
    quote: Any,
    reason: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """События quote.viewed, quote.accepted, quote.rejected."""
    deal = quote.deal
    company_id = deal.company_id
    payload: Dict[str, Any] = {
        "erp_quote_id": quote.id,
        "version": quote.version,
    }
    if reason:
        payload["reason"] = reason

    return emit_event(
        event_type=event_type,
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_contract_signed(
    contract: Any,
    by: str = "both",
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """Событие contract.signed."""
    deal = contract.deal
    company_id = deal.company_id
    payload: Dict[str, Any] = {
        "erp_contract_id": contract.id,
        "number": contract.number or f"CT-{contract.id}",
        "by": by,
    }

    return emit_event(
        event_type="contract.signed",
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_invoice_event(
    event_type: str,
    invoice: Any,
    link: Optional[str] = None,
    erp_document_id: Optional[int] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """События invoice.issued, invoice.paid, invoice.overdue."""
    deal = invoice.deal
    company_id = deal.company_id

    currency = "UZS"
    if getattr(invoice, "currency", None):
        c = invoice.currency
        currency = c.code if hasattr(c, "code") else str(c)

    due_date_str = invoice.due_date.isoformat() if invoice.due_date else timezone.now().date().isoformat()
    if not link:
        link = f"https://cabinet.railtech.uz/invoices/{invoice.id}"

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

    return emit_event(
        event_type=event_type,
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_delivery_event(
    event_type: str,
    fulfillment: Any,
    line_summary: str = "Строки поставки",
    line_nos: Optional[List[int]] = None,
    previous_eta: Optional[Any] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """События delivery.status_changed, delivery.eta_changed."""
    deal = fulfillment.deal
    company_id = deal.company_id

    status_str = "assembling"
    if getattr(fulfillment, "status", None):
        status_val = fulfillment.status.code if hasattr(fulfillment.status, "code") else str(fulfillment.status)
        status_str = status_val.lower()

    if status_str not in ("assembling", "in_transit", "ready_to_ship", "shipped", "delivered"):
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

    return emit_event(
        event_type=event_type,
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_act_event(
    event_type: str,
    act: Any,
    reason: Optional[str] = None,
    erp_document_id: Optional[int] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """События act.issued, act.accepted, act.returned."""
    deal = act.deal
    company_id = deal.company_id

    payload: Dict[str, Any] = {
        "erp_act_id": act.id,
        "number": act.number or f"ACT-{act.id}",
    }
    if reason:
        payload["reason"] = reason
    if erp_document_id:
        payload["erp_document_id"] = erp_document_id

    return emit_event(
        event_type=event_type,
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_document_created(
    document: Any,
    deal: Optional[Any] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """Событие document.created."""
    if deal is None and hasattr(document, "deal"):
        deal = document.deal
    company_id = deal.company_id if deal else getattr(document, "company_id", None)
    if not company_id:
        logger.warning("Document #%s has no associated company, skipping webhook", getattr(document, "id", None))
        return None

    raw_kind = ""
    if hasattr(document, "template") and document.template and hasattr(document.template, "kind"):
        raw_kind = document.template.kind.code
    elif hasattr(document, "kind"):
        raw_kind = str(document.kind)

    kind_map = {
        "quote": "quote",
        "kp": "quote",
        "contract": "contract",
        "dogovor": "contract",
        "invoice": "invoice",
        "schet": "invoice",
        "act": "act",
        "waybill": "waybill",
        "receipt": "receipt",
    }
    kind = kind_map.get(raw_kind.lower(), "other")

    payload: Dict[str, Any] = {
        "erp_document_id": document.id,
        "kind": kind,
        "number": getattr(document, "number", "") or f"DOC-{document.id}",
    }
    title = getattr(document, "title", None)
    if title:
        payload["title"] = title

    return emit_event(
        event_type="document.created",
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_invite_sent(
    contact: Any,
    channels: List[str],
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """Событие invite.sent."""
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

    return emit_event(
        event_type="invite.sent",
        erp_company_id=company_id,
        payload=payload,
        deal=None,
        actor=actor,
        send_async=send_async,
    )


#: Решение клиента по строке поставки → тип события (`events.schema.json`, `DeliveryLineDecision.status`).
DELIVERY_LINE_EVENTS = {"accepted": "delivery.line_accepted", "disputed": "delivery.line_disputed"}

#: `DeliveryLineDecision.remark.maxLength`.
DELIVERY_LINE_REMARK_MAX = 2000


def emit_delivery_line_decision(
    line: Any,
    contact: Any,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """События delivery.line_accepted / delivery.line_disputed: клиент принял или оспорил строку поставки (FIX-37).

    Решение уже записано в `line` (`status` — `accepted`/`disputed`, `accepted_at` — время решения, `remark` — замечание).
    Запись события создаётся в той же транзакции, что и решение (откат решения — нет события), а задача доставки
    ставится в очередь только после коммита (`emit_event`). Действующее лицо — клиент с именем контакта.
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

    return emit_event(
        event_type=event_type,
        erp_company_id=deal.company_id,
        payload=payload,
        deal=deal,
        actor=build_actor(actor_type="client", name=getattr(contact, "name", None) or None),
        occurred_at=decided_at,
        send_async=send_async,
    )
