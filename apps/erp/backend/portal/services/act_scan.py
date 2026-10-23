"""Скан подписанного акта при приёмке из портала (FIX-22, контракт 0.2.0 `POST /acts/{id}/accept {upload_id}`).

Клиент заранее грузит файл в `POST /uploads` (`PortalUpload`), потом приёмка ссылается на него по `upload_id`.
Здесь: проверка файла (PDF или изображение, сигнатура совпадает с расширением), копия содержимого в
`Act.signed_file` (его пишет `crm.services.billing.sign_act`) и запись документа `GeneratedDocument`, на которую
ссылается `Act.scan_document_id` в ответе и которую отдаёт `GET /documents` (вид `act`, номер `SCAN-<номер акта>`).
Файл у записи общий с `Act.signed_file` (одно хранилище, копий нет). `scan_document_id` — id документа из
`GET /documents` (`portal.services.documents.encode_document_id("generated", pk)`), а не сырой pk. QUESTIONS Q-FIX23-3.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterable, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone
from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus
from portal.exceptions import PortalValidationError
from portal.models import PortalUpload
from portal.services.documents import encode_document_id

from core.tenant import own_company
from core.validators import ALLOWED_IMAGE_EXTENSIONS, assert_content_matches_extension
from crm.constants import DocumentTemplateKindCode, GeneratedDocumentStatusCode

SCAN_EXTENSIONS = frozenset({".pdf"}) | frozenset(ALLOWED_IMAGE_EXTENSIONS)
SCAN_TEMPLATE_NAME = "Скан подписанного акта"


def scan_document_number(act) -> str:
    return f"SCAN-{act.number}"


def load_scan(company, upload_id, deal=None) -> tuple[PortalUpload, ContentFile]:
    """Файл из `PortalUpload` компании, проверенный и готовый к записи в `Act.signed_file`.

    Чужая или неизвестная загрузка — 422 `UPLOAD_NOT_FOUND` (существование чужого файла не выдаём); так же — загрузка,
    уже вложенная в заявку или другую сделку (`PortalUpload.deal` — не пусто и не сделка акта `deal`): её не
    переиспользуем и не перепривязываем; не PDF и не
    изображение, подделанная сигнатура или размер больше лимита контракта — 422 `VALIDATION_ERROR`.
    """
    try:
        key = uuid.UUID(str(upload_id))
    except ValueError:
        raise PortalValidationError("UPLOAD_NOT_FOUND")
    upload = PortalUpload.objects.filter(upload_id=key, company=company).first()
    if upload is None or (upload.deal_id is not None and (deal is None or upload.deal_id != deal.pk)):
        raise PortalValidationError("UPLOAD_NOT_FOUND")

    extension = os.path.splitext(upload.name)[1].lower()
    if extension not in SCAN_EXTENSIONS or upload.size_bytes > settings.PORTAL_UPLOAD_MAX_BYTES:
        raise PortalValidationError("VALIDATION_ERROR")
    try:
        with upload.file.open("rb") as stream:
            content = stream.read()
        assert_content_matches_extension(ContentFile(content, name=upload.name), label="Scan")
    except (OSError, ValidationError):
        raise PortalValidationError("VALIDATION_ERROR")
    return upload, ContentFile(content, name=upload.name)


def attach_scan_document(act, upload: PortalUpload) -> GeneratedDocument:
    """Документ-скан акта в списке документов сделки. Файл — тот же, что в `Act.signed_file` (после `sign_act`).

    Событие шины `document.created` (исходящий документ ERP) для входящего скана не публикуется (`document_events.publish_document_issued` его отсекает).
    """
    owner = own_company() or act.deal.company
    kind, _ = DocumentTemplateKind.objects.get_or_create(
        code=DocumentTemplateKindCode.ACT, defaults={"name": DocumentTemplateKindCode.ACT.label}
    )
    template, _ = DocumentTemplate.objects.get_or_create(
        company=owner, name=SCAN_TEMPLATE_NAME, defaults={"kind": kind, "is_active": False}
    )
    issued = GeneratedDocumentStatus.objects.get(code=GeneratedDocumentStatusCode.ISSUED)
    now = timezone.now()
    document = GeneratedDocument(
        company=owner,
        deal=act.deal,
        template=template,
        status=issued,
        number=scan_document_number(act),
        title=f"Скан подписанного акта {act.number}",
        values={"act_id": act.pk, "source": "portal_scan", "upload_id": str(upload.upload_id)},
        issued_at=now,
        pdf_file=act.signed_file.name,
    )
    GeneratedDocument.objects.bulk_create([document])
    upload.deal = act.deal
    upload.save(update_fields=["deal"])
    return GeneratedDocument.objects.get(number=document.number)


def annotate_scan_documents(acts: Iterable) -> None:
    """Ставит `act.portal_scan_document_id` одним запросом (в списке актов — без N+1)."""
    acts = list(acts)
    numbers = {scan_document_number(act) for act in acts if act.signed_file}
    found: dict = {}
    if numbers:
        # Только скан своей сделки и только заведённый приёмкой: номер `SCAN-…` уникален, но чужой документ с таким
        # номером ссылкой на скан становиться не должен.
        scans = GeneratedDocument.objects.filter(
            number__in=numbers, deal_id__in={act.deal_id for act in acts}, values__source="portal_scan"
        )
        found = {(scan.number, scan.deal_id): scan.pk for scan in scans}
    for act in acts:
        scan_pk = found.get((scan_document_number(act), act.deal_id))
        act.portal_scan_document_id = encode_document_id("generated", scan_pk) if scan_pk else None


def scan_document_id(act) -> Optional[int]:
    if not hasattr(act, "portal_scan_document_id"):
        annotate_scan_documents([act])
    return act.portal_scan_document_id
