"""Celery tasks for reliable delivery of ERP -> CRM webhooks (CONTRACTS §3, M3-ERP-02).

Ретраи ERP: 1, 5, 30 мин, 2, 6, 24 ч; после — журнал с ручным повтором.
Заголовки:
- X-Event-Id (UUID)
- X-Event-Type
- X-Timestamp (ISO-8601 with tz)
- X-Signature: sha256=<HMAC(body, ERP_WEBHOOK_SECRET)>
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx
from celery import shared_task
from celery.exceptions import Retry
from django.conf import settings
from django.utils import timezone

from .models import IntegrationWebhookEvent, WebhookEventStatus
from .services.webhooks import sign_payload

logger = logging.getLogger(__name__)

# Сетка повторов по CONTRACTS §3 (6 шагов: 1 мин, 5 мин, 30 мин, 2 ч, 6 ч, 24 ч)
RETRY_DELAYS = [60, 300, 1800, 7200, 21600, 86400]


@shared_task(bind=True, max_retries=len(RETRY_DELAYS))
def deliver_webhook_event(self, event_id: int) -> bool:
    """Доставляет исходящий вебхук события в CRM по HTTP.

    При сбое выполняет повторные попытки с экспоненциальным интервалом.
    После исчерпания попыток переводит событие в статус FAILED.
    """
    event = IntegrationWebhookEvent.objects.filter(pk=event_id).first()
    if not event:
        logger.warning("deliver_webhook_event: IntegrationWebhookEvent #%s not found", event_id)
        return False

    if event.status == WebhookEventStatus.SENT:
        logger.info("deliver_webhook_event: event #%s already SENT", event_id)
        return True

    event.attempts += 1
    event.last_attempt_at = timezone.now()

    secret = getattr(settings, "ERP_WEBHOOK_SECRET", "dev-erp-webhook-secret")
    body_bytes = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = sign_payload(secret, body_bytes)

    headers = {
        "Content-Type": "application/json",
        "X-Event-Id": str(event.event_id),
        "X-Event-Type": event.event_type,
        "X-Timestamp": event.payload.get("occurred_at", timezone.now().isoformat()),
        "X-Signature": signature,
    }
    event.headers = headers

    # Индекс текущей попытки для выбора задержки
    current_attempt = getattr(self.request, "retries", 0) if hasattr(self, "request") else 0
    if current_attempt == 0 and event.attempts > 1:
        current_attempt = event.attempts - 1

    has_retries_left = current_attempt < len(RETRY_DELAYS) and event.attempts <= len(RETRY_DELAYS)

    try:
        # CRM должна отвечать быстро (200 OK)
        with httpx.Client(timeout=10.0) as client:
            response = client.post(event.target_url, content=body_bytes, headers=headers)

        event.response_status = response.status_code

        if 200 <= response.status_code < 300:
            event.status = WebhookEventStatus.SENT
            event.sent_at = timezone.now()
            event.last_error = ""
            event.save(
                update_fields=[
                    "status",
                    "attempts",
                    "last_attempt_at",
                    "last_error",
                    "response_status",
                    "sent_at",
                    "headers",
                ]
            )
            logger.info(
                "Webhook event %s (%s) delivered successfully to %s: HTTP %s",
                event.event_id,
                event.event_type,
                event.target_url,
                response.status_code,
            )
            return True

        # Non-2xx HTTP response from CRM
        error_msg = f"HTTP {response.status_code}: {response.text[:500]}"
        event.last_error = error_msg
        if not has_retries_left:
            event.status = WebhookEventStatus.FAILED

        event.save(
            update_fields=[
                "status",
                "attempts",
                "last_attempt_at",
                "last_error",
                "response_status",
                "headers",
            ]
        )

        if has_retries_left:
            countdown = RETRY_DELAYS[current_attempt]
            logger.warning(
                "Webhook %s delivery failed (%s). Retrying in %ds (attempt %d/%d)",
                event.event_id,
                error_msg,
                countdown,
                current_attempt + 1,
                len(RETRY_DELAYS),
            )
            raise self.retry(countdown=countdown, exc=Exception(error_msg))

        logger.error(
            "Webhook %s delivery exhausted all %d retries. Marked as FAILED.",
            event.event_id,
            len(RETRY_DELAYS),
        )
        return False

    except Retry:
        raise
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        event.last_error = error_msg
        if not has_retries_left:
            event.status = WebhookEventStatus.FAILED

        event.save(
            update_fields=[
                "status",
                "attempts",
                "last_attempt_at",
                "last_error",
                "response_status",
                "headers",
            ]
        )

        if has_retries_left:
            countdown = RETRY_DELAYS[current_attempt]
            logger.warning(
                "Webhook %s exception: %s. Retrying in %ds (attempt %d/%d)",
                event.event_id,
                error_msg,
                countdown,
                current_attempt + 1,
                len(RETRY_DELAYS),
            )
            raise self.retry(countdown=countdown, exc=exc)

        logger.error(
            "Webhook %s delivery exception exhausted all %d retries. Marked as FAILED.",
            event.event_id,
            len(RETRY_DELAYS),
        )
        return False


def redeliver_event(event_id: int) -> Optional[IntegrationWebhookEvent]:
    """Ручной повтор отправки события из журнала (CONTRACTS §3)."""
    event = IntegrationWebhookEvent.objects.filter(pk=event_id).first()
    if not event:
        return None

    event.status = WebhookEventStatus.PENDING
    event.save(update_fields=["status"])
    deliver_webhook_event.delay(event.id)
    return event
