"""Задачи интеграции (Celery)."""

from __future__ import annotations

import logging

from celery import shared_task
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

MAX_RETRIES = 5


def _finish(deal_id: int, *, attached: bool, reason: str = "") -> None:
    """Расчёт больше не ждёт файл: пришёл он или нет; не пришёл — запись в журнале заявки."""
    from sales.models import CalcTask, Deal

    from crm.services import calc_tasks

    CalcTask.objects.filter(deal_id=deal_id, eds_letter_id__isnull=True).update(request_file_pending=False)
    if attached:
        return
    deal = Deal.objects.filter(pk=deal_id).first()
    calc_tasks.deal_log(
        deal,
        "Файл письма клиента не получен",
        f"Файл основания заявки не удалось взять в расчёт ({reason}); откройте письмо клиента вручную",
        event_code="deal.request_file_missing",
        event_params={"reason": reason},
        level="WARNING",
    )


@shared_task(bind=True, name="integration.fetch_request_letter_file", max_retries=MAX_RETRIES)
def fetch_request_letter_file(self, deal_id: int, file_id: str, created_by: int, letter_number: str = "") -> bool:
    """Файл письма клиента → исходники заявки (`deal_request_files`). Идемпотентно: тот же файл второй раз не кладётся."""
    from sourcing.models import Attachment, AttachmentKind

    from .services import eds_files

    try:
        found = eds_files.fetch_request_file(file_id, created_by, letter_number)
    except eds_files.EdsFileUnavailable as exc:
        if self.request.retries >= MAX_RETRIES:
            _finish(deal_id, attached=False, reason="eds_unavailable")
            return False
        raise self.retry(exc=exc, countdown=min(30 * 2**self.request.retries, 900))
    if found is None:
        _finish(deal_id, attached=False, reason="not_found")
        return False
    name, data = found
    already = Attachment.objects.filter(deal_id=deal_id, kind=AttachmentKind.SOURCE, original_filename=name).exists()
    if not already:
        Attachment.objects.create(
            deal_id=deal_id, kind=AttachmentKind.SOURCE, original_filename=name, file=ContentFile(data, name=name)
        )
    _finish(deal_id, attached=True)
    return True
