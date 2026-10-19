"""Скан подписанного акта при приёмке из портала (FIX-22, контракт 0.2.0 `POST /acts/{id}/accept {upload_id}`).

Клиент заранее грузит файл в `POST /uploads` (`PortalUpload`), потом приёмка ссылается на него по `upload_id`.
Здесь: проверка файла (PDF или изображение, сигнатура совпадает с расширением), копия содержимого в
`Act.signed_file` (его пишет `crm.services.billing.sign_act`) и запись документа `GeneratedDocument`, на которую
ссылается `Act.scan_document_id` в ответе и которую отдаёт `GET /documents` (вид `act`, номер `SCAN-<номер акта>`).
Файл у записи общий с `Act.signed_file` (одно хранилище, копий нет). QUESTIONS Q-FIX22-3.
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

from core.tenant import own_company
from core.validators import ALLOWED_IMAGE_EXTENSIONS, assert_content_matches_extension
from crm.constants import DocumentTemplateKindCode, GeneratedDocumentStatusCode

SCAN_EXTENSIONS = frozenset({".pdf"}) | frozenset(ALLOWED_IMAGE_EXTENSIONS)
SCAN_TEMPLATE_NAME = "Скан подписанного акта"


def scan_document_number(act) -> str:
    return f"SCAN-{act.number}"


def load_scan(company, upload_id) -> tuple[PortalUpload, ContentFile]:
    """Файл из `PortalUpload` компании, проверенный и готовый к записи в `Act.signed_file`.

    Чужая или неизвестная загрузка — 422 `UPLOAD_NOT_FOUND` (существование чужого файла не выдаём); не PDF и не
    изображение, подделанная сигнатура или размер больше лимита контракта — 422 `VALIDATION_ERROR`.
    """
    try:
        key = uuid.UUID(str(upload_id))
    except ValueError:
        raise PortalValidationError("UPLOAD_NOT_FOUND")
    upload = PortalUpload.objects.filter(upload_id=key, company=company).first()
    if upload is None:
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

    Запись заводится `bulk_create`: сигнал `document.created` (исходящий документ ERP) для входящего скана не нужен.
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
    numbers = {scan_document_number(act): act for act in acts if act.signed_file}
    found = dict(GeneratedDocument.objects.filter(number__in=numbers).values_list("number", "id")) if numbers else {}
    for act in acts:
        act.portal_scan_document_id = found.get(scan_document_number(act))


def scan_document_id(act) -> Optional[int]:
    if not hasattr(act, "portal_scan_document_id"):
        annotate_scan_documents([act])
    return act.portal_scan_document_id
