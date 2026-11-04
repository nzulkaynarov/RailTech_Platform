"""Загрузка прайса партнёром из кабинета (PART-2): тот же движок, что у сотрудника (`sourcing/catalog_import.py`), другой вход.

Поставщик — компания сессии, выбрать другого нельзя; автор — контакт (`ImportTask.contact`, `ProductFieldProposal.contact`);
новые карточки — нашего каталога (владелец — своя компания), партнёр — источник данных. Предпросмотр (`dry_run`) гонит те же
проверки и ничего не пишет. Задача асинхронная (Celery), как у сотрудника; статус читается по `ImportTask` компании сессии:
чужой или несуществующий `task_id` — 404.

Отчёт для партнёра — белый список: счётчики, строки с ошибками и поля предложений. Названия и значения чужих карточек
(`product_name`, `current`, `proposed` из отчёта движка) наружу не уходят.
"""

from __future__ import annotations

import base64
import logging
import re

from ai.models import ImportTask
from celery.result import AsyncResult
from django.db import DatabaseError
from django.utils.dateparse import parse_date
from kombu.exceptions import OperationalError
from portal.exceptions import PortalBadRequest, PortalUnavailable, PortalValidationError

from catalog.services import offer_validity_error
from core.tenant import own_company_id
from sourcing.tasks import process_catalog_import
from sourcing.views_imports import MAX_EXCEL_FILE_SIZE, _validate_xlsx_signature

logger = logging.getLogger(__name__)

TRUE_VALUES = ("1", "true", "yes", "on")
ERROR_CODE_SHAPE = re.compile(r"^[A-Z][A-Z0-9_]+$")


def is_true(value) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def parse_validity(data) -> dict:
    """Срок действия цен на весь файл из формы → `{valid_from, valid_until}` (строки `ГГГГ-ММ-ДД`)."""
    out = {}
    for name in ("valid_from", "valid_until"):
        raw = str(data.get(name) or "").strip()
        if not raw:
            continue
        try:
            value = parse_date(raw)
        except ValueError:
            value = None
        if value is None:
            raise PortalValidationError("VALID_DATE_INVALID")
        out[name] = value.isoformat()
    error = offer_validity_error(out.get("valid_from"), out.get("valid_until"))
    if error:
        raise PortalValidationError(error)
    return out


def read_workbook(file_obj) -> bytes:
    """Файл формы → байты: размер и подпись `.xlsx` — как у сотрудника (20 МБ, `PK\\x03\\x04`)."""
    if file_obj is None:
        raise PortalBadRequest("FILE_REQUIRED")
    if file_obj.size > MAX_EXCEL_FILE_SIZE:
        raise PortalValidationError("FILE_TOO_LARGE")
    content = file_obj.read()
    if not _validate_xlsx_signature(content):
        raise PortalBadRequest("XLSX_REQUIRED")
    return content


def enqueue_price_list(*, company, contact, content: bytes, dry_run: bool, validity: dict) -> str:
    """Поставить загрузку в очередь → `task_id`. Владелец новых карточек — своя компания; её нет — загрузка недоступна."""
    owner_id = own_company_id()
    if owner_id is None:
        raise PortalUnavailable("IMPORT_FAILED")
    try:
        task = process_catalog_import.delay(
            base64.b64encode(content).decode("ascii"),
            company.pk,
            dry_run,
            owner_company_id=owner_id,
            contact_id=contact.pk,
            **validity,
        )
        ImportTask.objects.create(celery_task_id=task.id, contact=contact, task_type="CATALOG_IMPORT")
    except (OSError, ValueError, DatabaseError, OperationalError):
        logger.exception("Failed to queue partner price list")
        raise PortalUnavailable("IMPORT_FAILED") from None
    return task.id


def async_result(task_id: str):
    """Результат задачи Celery — отдельной функцией, чтобы тесты подставляли его без брокера."""
    return AsyncResult(task_id)


def task_for_company(company, task_id: str):
    """Задача импорта, запущенная контактом этой компании; чужая и несуществующая — `None` (404)."""
    return ImportTask.objects.filter(
        celery_task_id=task_id, contact__company_id=company.pk, task_type="CATALOG_IMPORT"
    ).first()


def _file_error(message) -> str:
    """Код ошибки уровня файла; всё, что не код (текст исключения), — общий `IMPORT_FAILED`."""
    return message if isinstance(message, str) and ERROR_CODE_SHAPE.match(message) else "IMPORT_FAILED"


#: Код проблемы строки движка → колонка шаблона (`PriceListField` контракта). Нет в таблице — `field: null`, кабинет
#: покажет общий текст «строка не загружена».
ISSUE_FIELDS = {
    "PRICE_NOT_A_NUMBER": "price",
    "PRICE_NOT_POSITIVE": "price",
    "UNKNOWN_CATEGORY": "category",
    "UNKNOWN_DOMAIN": "domain_type",
    "UNKNOWN_CURRENCY": "currency",
    "UNKNOWN_STOCK_STATUS": "stock",
    "VALID_DATE_INVALID": "valid_from",
    "OFFER_VALIDITY_RANGE_INVALID": "valid_until",
    "HS_CODE_TOO_LONG": "hs_code",
    "HS_CODE_NOT_IN_CLASSIFIER": "hs_code",
    "HS_CODE_RETIRED": "hs_code",
}


def _issue(item: dict) -> dict:
    """Проблема строки движка `"КОД"` или `"КОД:значение"` → `{row, field, code, value}`: что в какой колонке исправить."""
    code, _sep, value = str(item["message"]).partition(":")
    return {"row": item["row"], "field": ISSUE_FIELDS.get(code), "code": code, "value": value or None}


def _issues(items) -> list[dict]:
    return [_issue(item) for item in items or []]


def report_view(raw: dict) -> dict:
    """Отчёт движка → `PriceListReport` (белый список; поля чужих карточек наружу не идут)."""
    return {
        "dry_run": bool(raw.get("dry_run")),
        "created": raw.get("created") or 0,
        "updated": raw.get("updated") or 0,
        "offers_created": raw.get("offers_created") or 0,
        "offers_updated": raw.get("offers_updated") or 0,
        "proposal_count": raw.get("proposal_count") or 0,
        "proposals": [{"row": item["row"], "field": item["field"]} for item in raw.get("proposals") or []],
        "error_count": raw.get("error_count") or 0,
        "errors": _issues(raw.get("errors")),
        "warning_count": raw.get("warning_count") or 0,
        "warnings": _issues(raw.get("warnings")),
        "rows_truncated": raw.get("rows_truncated") or 0,
        "unpublishable": raw.get("unpublishable") or 0,
        "missing_breakdown": [
            {"code": item["code"], "label": str(item["label"]), "count": item["count"]}
            for item in raw.get("missing_breakdown") or []
        ],
    }


def task_view(task_id: str) -> dict:
    """Состояние задачи для кабинета: `pending | running | completed | failed` и отчёт."""
    result = async_result(task_id)
    state = result.state
    base = {"task_id": task_id, "error": None, "report": None}
    if state == "FAILURE":
        return {**base, "status": "failed", "error": "IMPORT_FAILED"}
    if state != "SUCCESS":
        return {**base, "status": "running" if state in ("STARTED", "PROGRESS", "RETRY") else "pending"}
    raw = result.result
    if not isinstance(raw, dict):
        return {**base, "status": "failed", "error": "IMPORT_FAILED"}
    if raw.get("status") == "error":
        return {**base, "status": "failed", "error": _file_error(raw.get("message"))}
    return {**base, "status": "completed", "report": report_view(raw)}
