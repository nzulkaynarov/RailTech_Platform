"""Webhook dispatch service for ERP -> CRM events (CONTRACTS §3, M3-ERP-02).

Спецификация вебхуков: POST {CRM}/api/v1/integrations/erp/events.
Заголовки:
- X-Event-Id (UUIDv4)
- X-Event-Type
- X-Timestamp (UTC ISO 8601, момент отправки этой попытки)
- X-Signature: sha256=<HMAC(secret, "{X-Event-Id}.{X-Timestamp}.{body}")> — схема v2 (FIX-61, Q-FIX35-2)

Тело и валидация соответствуют JSON-схеме `packages/contracts/events.schema.json`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import timezone as dt_timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from portal import projections

from ..models import CrmClientMapping, CrmContactMapping, IntegrationWebhookEvent, WebhookEventStatus
from . import credentials, event_contract, stages

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = {
    "request.created",
    "deal.stage_changed",
    "quote.sent",
    "quote.viewed",
    "quote.accepted",
    "quote.rejected",
    "quote.acceptance_code_requested",
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


def webhook_signing_secret() -> str:
    """Секрет, которым ERP подписывает вебхуки сейчас (FIX-35, M3-ERP-05).

    Источник — `credentials.webhook_secret()`: секрет, выданный сопряжением (БД, шифрованно), иначе `ERP_WEBHOOK_SECRET`
    из окружения — один секрет либо список через запятую: подписывает ПЕРВЫЙ, остальные остаются в списке, чтобы обе
    стороны хранили одну и ту же строку на время ротации. CRM принимает текущий и предыдущий секрет
    (docs/runbooks/webhooks.md, «Ротация секрета»). Пусто — секрета нет.
    """
    return credentials.webhook_secret()


def sign_payload(secret: str, body_bytes: bytes) -> str:
    """Старая подпись (схема v1): HMAC-SHA256 только по телу, `sha256=<hex>`.

    ERP так больше не подписывает (FIX-61); функция осталась как эталон старой схемы для тестов совместимости.
    """
    signature = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


def signature_timestamp() -> str:
    """`X-Timestamp` попытки доставки: сейчас, UTC, ISO 8601 с `Z` и точностью до секунды (CONTRACTS §3)."""
    return timezone.now().astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sign_payload_v2(secret: str, event_id: Any, timestamp: str, body_bytes: bytes) -> str:
    """Подпись v2 (FIX-61): `sha256=HMAC(secret, "{X-Event-Id}.{X-Timestamp}.{body}")`.

    Подписанная строка собирается из байтов: `event_id` и `timestamp` — ровно как уходят в заголовках, `body_bytes` —
    ровно как уходят в запросе. Тело под чужим `X-Event-Id` или со старой меткой даёт другую подпись.
    """
    signed = f"{event_id}.{timestamp}.".encode() + body_bytes
    return f"sha256={hmac.new(secret.encode('utf-8'), signed, hashlib.sha256).hexdigest()}"


def verify_signature_v2(secret: str, event_id: Any, timestamp: str, body_bytes: bytes, signature_header: str) -> bool:
    """Проверяет `X-Signature` схемы v2."""
    expected = sign_payload_v2(secret, event_id, timestamp, body_bytes)
    return hmac.compare_digest(expected.encode(), signature_header.strip().encode())


def verify_signature(secret: str, body_bytes: bytes, signature_header: str) -> bool:
    """Проверяет заголовок `X-Signature` старой схемы (только тело)."""
    expected = sign_payload(secret, body_bytes)
    return hmac.compare_digest(expected, signature_header.strip())


# ── Секреты в теле события (FIX-60a, Q-FIX22-1) ─────────────────────────────────────────────────────────────────────
#
# Одноразовый код акцепта (`quote.acceptance_code_requested`, `payload.code`) должен дойти до бота CRM, но не осесть ни в
# журнале доставки (`IntegrationWebhookEvent.payload` видна в админке и в бэкапах), ни в логах. Поэтому в журнал пишется
# тело с маской, а настоящее значение лежит только в кэше (Redis) под ключом события на время жизни кода — оттуда его
# берёт задача доставки и кладёт в тело запроса. Кэша нет (код протух, Redis перезапущен) — доставка не повторяется:
# событие переходит в `FAILED` с пометкой, а клиент запрашивает новый код.

#: Поля `payload`, значения которых секретны: тип события → имена полей.
SECRET_PAYLOAD_FIELDS: Dict[str, tuple] = {"quote.acceptance_code_requested": ("code",)}

#: Что вместо значения секретного поля остаётся в журнале.
SECRET_MASK = "***"

#: Сколько секрет живёт в кэше: срок кода акцепта (15 минут) с запасом на очередь Celery.
SECRET_PAYLOAD_TTL = 20 * 60


def _secret_cache_key(event_id: Any) -> str:
    return f"integration:webhook-secret:{event_id}"


def mask_secret_payload(event_type: str, payload: Dict[str, Any]) -> tuple:
    """(`payload` для журнала, секретные значения): поля из `SECRET_PAYLOAD_FIELDS` заменены на `SECRET_MASK`."""
    fields = SECRET_PAYLOAD_FIELDS.get(event_type, ())
    secrets_found = {name: payload[name] for name in fields if name in payload}
    if not secrets_found:
        return payload, {}
    return {**payload, **{name: SECRET_MASK for name in secrets_found}}, secrets_found


def stash_secret_payload(event_id: Any, secrets_found: Dict[str, Any]) -> None:
    from django.core.cache import cache

    cache.set(_secret_cache_key(event_id), secrets_found, SECRET_PAYLOAD_TTL)


def delivery_payload(event: IntegrationWebhookEvent) -> Optional[Dict[str, Any]]:
    """Тело события для отправки: журнал плюс секреты из кэша. `None` — секрет потерян (протух), отправлять нечего."""
    fields = SECRET_PAYLOAD_FIELDS.get(event.event_type)
    if not fields:
        return event.payload
    from django.core.cache import cache

    secrets_found = cache.get(_secret_cache_key(event.event_id))
    if not secrets_found or any(name not in secrets_found for name in fields):
        return None
    return {**event.payload, "payload": {**event.payload["payload"], **secrets_found}}


def discard_secret_payload(event: IntegrationWebhookEvent) -> None:
    """Секрет больше не нужен (событие доставлено): убрать из кэша, не дожидаясь срока."""
    if event.event_type in SECRET_PAYLOAD_FIELDS:
        from django.core.cache import cache

        cache.delete(_secret_cache_key(event.event_id))


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
    secret = webhook_signing_secret()
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
    # Форма тела — по events.schema.json: в DEBUG и в тестах несоответствие — исключение, в проде — запись в лог (FIX-35).
    event_contract.check_envelope(envelope)

    event_id = uuid.uuid4()
    webhook_url = settings.CRM_WEBHOOK_URL

    body_bytes = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # Секретное поле (код акцепта) в журнал не попадает: туда — тело с маской, настоящее значение — в кэш (см. выше).
    journal_payload, secret_values = mask_secret_payload(event_type, envelope["payload"])

    headers = {
        "Content-Type": "application/json",
        "X-Event-Id": str(event_id),
        "X-Event-Type": event_type,
        "X-Timestamp": signature_timestamp(),
    }
    if secret:
        # Справочная подпись первой попытки; при каждой отправке (и ретрае) задача доставки подписывает заново (FIX-61).
        headers["X-Signature"] = sign_payload_v2(secret, event_id, headers["X-Timestamp"], body_bytes)

    event_obj = IntegrationWebhookEvent.objects.create(
        event_id=event_id,
        event_type=event_type,
        target_url=webhook_url,
        payload={**envelope, "payload": journal_payload} if secret_values else envelope,
        headers=headers,
        status=WebhookEventStatus.PENDING,
    )
    if secret_values:
        # Секрет — в кэш только после записи в журнал: упавший `create` не оставляет в кэше значение без события.
        stash_secret_payload(event_id, secret_values)

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


def _cabinet_url() -> str:
    """Адрес Cabinet из настроек (`CABINET_URL`), без хвостового слэша: ссылки событий не зашивают прод-домен."""
    return getattr(settings, "CABINET_URL", "http://cabinet.localhost").rstrip("/")


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

    return emit_event(
        event_type="quote.sent",
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def contact_refs(contact: Any) -> Dict[str, Any]:
    """`erp_contact_id` и `crm_contact_id` контакта для тела события (CRM-идентификатор — `null`, если не сопоставлен)."""
    crm_contact_id = CrmContactMapping.objects.filter(contact=contact).values_list("crm_contact_id", flat=True).first()
    return {"erp_contact_id": contact.id, "crm_contact_id": crm_contact_id}


def emit_quote_outcome(
    event_type: str,
    quote: Any,
    reason: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
    contact: Optional[Any] = None,
) -> Optional[IntegrationWebhookEvent]:
    """События quote.viewed, quote.accepted, quote.rejected.

    `contact` — контакт клиента, принявший или отклонивший КП в Cabinet (Q-FIX22-6): в `payload` уходят `erp_contact_id`
    и `crm_contact_id` (`null`, если контакт не сопоставлен), действующее лицо — клиент с именем контакта. Без контакта
    (публичная страница КП, менеджер) полей нет.
    """
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
            actor = build_actor(actor_type="client", name=getattr(contact, "name", None) or None)

    return emit_event(
        event_type=event_type,
        erp_company_id=company_id,
        payload=payload,
        deal=deal,
        actor=actor,
        send_async=send_async,
    )


def emit_quote_acceptance_code_requested(
    quote: Any,
    contact: Any,
    code: str,
    expires_at: Any,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """Событие quote.acceptance_code_requested: клиент запросил код акцепта в Cabinet, код доставит бот CRM (Q-FIX22-1).

    Шлётся только контакту, сопоставленному с контактом CRM (`crm_contact_id`): иначе боту некому писать — `None`, и
    вызывающий код отправляет код письмом. `code` — секрет: в журнал доставки он не попадает (маска), в логи не пишется.
    """
    crm_contact_id = CrmContactMapping.objects.filter(contact=contact).values_list("crm_contact_id", flat=True).first()
    if not crm_contact_id:
        return None
    deal = quote.deal
    return emit_event(
        event_type="quote.acceptance_code_requested",
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
        actor=build_actor(actor_type="client", name=getattr(contact, "name", None) or None),
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

    # Принято и оспорено клиентом — физически это «доставлено»; в `DeliveryEvent.status` контракта значений
    # `accepted`/`disputed` нет (решения клиента — в `delivery.line_accepted|disputed`), а прежняя подстановка
    # `assembling` для них была неправдой (FIX-62, Q-FIX62-1).
    status_str = {"accepted": "delivered", "disputed": "delivered"}.get(status_str, status_str)
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
    actor: Optional[Dict[str, Any]] = None,
    send_async: bool = True,
) -> Optional[IntegrationWebhookEvent]:
    """Событие document.created: клиенту выпущен документ (FIX-38).

    `document` — `portal.services.documents.PortalDocument`, то есть уже выпущенный и видимый клиенту документ;
    `erp_document_id` — его идентификатор портала (тот же, что в `GET /deals/{id}/documents` и у ссылки на файл),
    `kind` — вид документа (КП, договор, счёт, акт, накладная). Черновики и внутренние документы сюда не попадают:
    их отсекает `signals.handle_document_post_save` по правилу выпуска портала.
    """
    deal = document.deal
    contact = getattr(document.obj, "contact", None) if deal is None else None
    company_id = deal.company_id if deal is not None else getattr(contact, "company_id", None)
    if not company_id:
        logger.warning("Document #%s has no associated company, skipping webhook", document.id)
        return None

    payload: Dict[str, Any] = {
        "erp_document_id": document.id,
        "kind": document.kind,
        "number": document.number or f"DOC-{document.id}",
    }
    if document.title:
        payload["title"] = document.title

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
