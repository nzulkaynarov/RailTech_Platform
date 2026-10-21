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
from datetime import timedelta
from typing import Optional

import httpx
from celery import shared_task
from celery.exceptions import Retry
from django.db.models import Q
from django.utils import timezone

from core.log_mask import mask_secrets

from .models import IntegrationWebhookEvent, WebhookEventStatus
from .services.webhooks import delivery_payload, discard_secret_payload, sign_payload, webhook_signing_secret

logger = logging.getLogger(__name__)

# Сетка повторов по CONTRACTS §3 (6 шагов: 1 мин, 5 мин, 30 мин, 2 ч, 6 ч, 24 ч)
RETRY_DELAYS = [60, 300, 1800, 7200, 21600, 86400]

# Сколько PENDING-событие может просрочить плановое время попытки, прежде чем Beat сочтёт его зависшим (FIX-33):
# задача потеряна (рестарт Redis, воркер убит между acks), а не ждёт своего ретрая.
STUCK_GRACE = timedelta(minutes=10)
SWEEP_BATCH = 200


def _register_failure(event: IntegrationWebhookEvent, error_msg: str, has_retries_left: bool, current_attempt: int):
    """Итог неудачной попытки: FAILED, если ретраи кончились, иначе PENDING с плановым временем следующей."""
    event.last_error = mask_secrets(error_msg)  # FIX-66b: эхо заголовков/ключей в ответе CRM не оседает в БД
    if has_retries_left:
        event.next_attempt_at = timezone.now() + timedelta(seconds=RETRY_DELAYS[current_attempt])
    else:
        event.status = WebhookEventStatus.FAILED
        event.next_attempt_at = None
    event.save(
        update_fields=[
            "status",
            "next_attempt_at",
            "attempts",
            "last_attempt_at",
            "last_error",
            "response_status",
            "headers",
        ]
    )


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

    secret = webhook_signing_secret()
    if not secret:
        # Без секрета подписать нечем: событие остаётся PENDING (попытка не засчитана), его заберёт задача Beat,
        # когда секрет появится (FIX-33, «неподписанная доставка не теряется»).
        logger.error("deliver_webhook_event: ERP_WEBHOOK_SECRET is not configured, event #%s waits", event_id)
        return False

    # Тело отправки = журнал + секреты из кэша (код акцепта в журнале замаскирован, FIX-60a). Секрет протух — отправлять
    # нечего и повторять незачем: клиент запросит новый код.
    payload = delivery_payload(event)
    if payload is None:
        # Условное обновление: параллельная доставка могла уже записать SENT (и убрать секрет) — её итог не затираем.
        cancelled = IntegrationWebhookEvent.objects.filter(pk=event.pk, status=WebhookEventStatus.PENDING).update(
            status=WebhookEventStatus.FAILED,
            last_error="SECRET_EXPIRED: секретное поле тела события недоступно (срок кода вышел), отправка отменена",
            next_attempt_at=None,
        )
        if cancelled:
            logger.warning(
                "deliver_webhook_event: event #%s (%s) lost its secret payload, not sent", event_id, event.event_type
            )
        return False

    event.attempts += 1
    event.last_attempt_at = timezone.now()
    body_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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
            event.next_attempt_at = None
            event.save(
                update_fields=[
                    "status",
                    "next_attempt_at",
                    "attempts",
                    "last_attempt_at",
                    "last_error",
                    "response_status",
                    "sent_at",
                    "headers",
                ]
            )
            discard_secret_payload(event)
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
        _register_failure(event, error_msg, has_retries_left, current_attempt)

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
        _register_failure(event, error_msg, has_retries_left, current_attempt)

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
    """Ручной повтор отправки события из журнала (CONTRACTS §3): полный цикл ретраев с нуля.

    Счётчик попыток обнуляется — иначе «Повторить» после исчерпанной сетки делал бы одну попытку и снова FAILED.
    """
    event = IntegrationWebhookEvent.objects.filter(pk=event_id).first()
    if not event:
        return None

    event.status = WebhookEventStatus.PENDING
    event.attempts = 0
    event.next_attempt_at = timezone.now() + STUCK_GRACE
    event.save(update_fields=["status", "attempts", "next_attempt_at"])
    deliver_webhook_event.delay(event.id)
    return event


@shared_task(name="integration.requeue_stuck_webhook_events")
def requeue_stuck_webhook_events(batch: int = SWEEP_BATCH) -> int:
    """Beat (раз в 5 мин): ставит повтор доставки для зависших PENDING (FIX-33, I-7).

    Зависшее — PENDING, у которого плановое время попытки (`next_attempt_at`; у новых событий — `created_at`)
    прошло больше `STUCK_GRACE` назад: задачу потеряли (рестарт Redis, воркер убит), либо доставка ждала секрет.
    Событие, которое ждёт СВОЕГО ретрая (в будущем), не трогаем. Подобранному сдвигаем плановое время вперёд,
    чтобы следующий проход не ставил вторую задачу, пока первая ждёт воркера; дубль, если он всё же случится,
    CRM гасит по `X-Event-Id`.
    """
    now = timezone.now()
    horizon = now - STUCK_GRACE
    stuck = (
        IntegrationWebhookEvent.objects.filter(status=WebhookEventStatus.PENDING)
        .filter(Q(next_attempt_at__lt=horizon) | Q(next_attempt_at__isnull=True, created_at__lt=horizon))
        .order_by("created_at")
        .values_list("pk", "next_attempt_at")[:batch]
    )
    requeued = 0
    for pk, planned in list(stuck):
        # Захват строки: параллельный проход (или ручной «Повторить») не поставит вторую задачу.
        claimed = IntegrationWebhookEvent.objects.filter(
            pk=pk, status=WebhookEventStatus.PENDING, next_attempt_at=planned
        ).update(next_attempt_at=now + STUCK_GRACE)
        if claimed:
            deliver_webhook_event.delay(pk)
            requeued += 1
    if requeued:
        logger.warning("requeue_stuck_webhook_events: %d stuck PENDING event(s) requeued", requeued)
    return requeued
