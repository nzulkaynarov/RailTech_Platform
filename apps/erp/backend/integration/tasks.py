"""Задачи интеграции (Celery)."""

from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import Retry, SoftTimeLimitExceeded
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
#: Сеть и хранилище не должны держать воркер: мягкий предел — запись в журнал, жёсткий — подстраховка.
SOFT_TIME_LIMIT = 60
TIME_LIMIT = 90


def _finish(deal_id: int, *, attached: bool, reason: str = "") -> None:
    """Расчёт больше не ждёт файл — пришёл он или нет. Не пришёл — запись в журнале заявки (заявки нет — писать некуда)."""
    from sales.models import CalcTask, Deal

    from crm.services import calc_tasks

    CalcTask.objects.filter(deal_id=deal_id, eds_letter_id__isnull=True).update(request_file_pending=False)
    if attached:
        return
    deal = Deal.objects.filter(pk=deal_id).first()
    if deal is None:
        return
    calc_tasks.deal_log(
        deal,
        "Файл письма клиента не получен",
        f"Файл основания заявки не удалось взять в расчёт ({reason}); откройте письмо клиента вручную",
        event_code="deal.request_file_missing",
        event_params={"reason": reason},
        level="WARNING",
    )


def enqueue_request_letter_file(deal_id: int, file_id: str, created_by: int) -> None:
    """Поставить задачу после коммита. Не поставилась (брокер недоступен) — расчёт не ждёт файл вечно: флаг снят, запись в
    журнале заявки."""
    try:
        fetch_request_letter_file.delay(deal_id, file_id, created_by)
    except Exception:  # noqa: BLE001 — любой сбой постановки: брокер, сериализация
        logger.exception("fetch_request_letter_file: not enqueued, deal %s", deal_id)
        _finish(deal_id, attached=False, reason="queue_unavailable")


@shared_task(
    bind=True,
    name="integration.fetch_request_letter_file",
    max_retries=MAX_RETRIES,
    soft_time_limit=SOFT_TIME_LIMIT,
    time_limit=TIME_LIMIT,
)
def fetch_request_letter_file(self, deal_id: int, file_id: str, created_by: int) -> bool:
    """Файл письма клиента → исходники заявки (`deal_request_files`). Идемпотентно: тот же файл второй раз не кладётся.

    Любой окончательный сбой — EDS не отдаёт файл, хранилище не приняло, заявка исчезла, вышло время — снимает «файл
    загружается» и пишет в журнал заявки; расчёт не остаётся в ожидании."""
    from sales.models import Deal

    from sourcing.models import Attachment, AttachmentKind

    from .services import eds_files

    try:
        if not Deal.objects.filter(pk=deal_id).exists():
            _finish(deal_id, attached=False, reason="deal_gone")
            return False
        try:
            found = eds_files.fetch_request_file(file_id, created_by)
        except eds_files.EdsFileUnavailable as exc:
            if self.request.retries >= MAX_RETRIES:
                _finish(deal_id, attached=False, reason="eds_unavailable")
                return False
            raise self.retry(exc=exc, countdown=min(30 * 2**self.request.retries, 900))
        if found is None:
            _finish(deal_id, attached=False, reason="not_found")
            return False
        name, data = found
        already = Attachment.objects.filter(
            deal_id=deal_id, kind=AttachmentKind.SOURCE, original_filename=name
        ).exists()
        if not already:
            Attachment.objects.create(
                deal_id=deal_id, kind=AttachmentKind.SOURCE, original_filename=name, file=ContentFile(data, name=name)
            )
    except Retry:
        raise
    except SoftTimeLimitExceeded:
        _finish(deal_id, attached=False, reason="timeout")
        return False
    except Exception:  # noqa: BLE001 — хранилище, база: окончательный сбой, не оставляем расчёт в ожидании
        logger.exception("fetch_request_letter_file: failed, deal %s", deal_id)
        _finish(deal_id, attached=False, reason="storage_error")
        return False
    _finish(deal_id, attached=True)
    return True
