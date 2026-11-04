"""Документы карточки товара в портале (CAT-CARD-2): кто и какой файл может скачать, имя файла, аудит выдачи.

Правило видимости одно, им же пользуется и список `CatalogItem.documents` (`catalog.published.client_documents`): карточка
опубликована, документ привязан к ней, отмечен «видно клиенту» и действует (срок «действует до» не прошёл, пусто — бессрочно).
Иначе `None` — для API это 404, одинаковый для скрытого, просроченного, чужого и несуществующего документа.

Имя файла строится из названия документа и расширения хранимого файла; имя загруженного файла (`original_name`) клиенту не
отдаётся — в нём бывает имя поставщика (ORCHESTRATOR §3.5).
"""

from __future__ import annotations

import mimetypes
import os
import re

from django.db.models import Q
from django.utils import timezone

from catalog.models import TechDocument
from catalog.published import published_products
from core.file_streaming import storage_file_response

_UNSAFE_FILENAME = re.compile(r"[^\w\-.]+", flags=re.UNICODE)
_MAX_STEM = 80


def find_client_document(product_id: int, document_id: int) -> TechDocument | None:
    """Документ опубликованной карточки, видимый клиенту и действующий; иначе `None`."""
    if not published_products().filter(pk=product_id).exists():
        return None
    today = timezone.localdate()
    return (
        TechDocument.objects.filter(pk=document_id, product_id=product_id, client_visible=True)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .first()
    )


def download_name(document: TechDocument) -> str:
    """Название документа + расширение хранимого файла: `Сертификат_соответствия.pdf`."""
    stem = _UNSAFE_FILENAME.sub("_", (document.title or "").strip()).strip("_.")[:_MAX_STEM].strip("_.")
    extension = os.path.splitext(document.file.name)[1].lower()
    return f"{stem or f'document-{document.pk}'}{extension}"


def content_type(document: TechDocument) -> str:
    return mimetypes.guess_type(document.file.name)[0] or document.content_type or "application/octet-stream"


def file_response(document: TechDocument):
    """Поток файла из приватного хранилища (вложение) или `None`, если файл потерян в хранилище."""
    if not document.file:
        return None
    try:
        response = storage_file_response(
            document.file.storage,
            document.file.name,
            content_type=content_type(document),
            as_attachment=True,
            filename=download_name(document),
        )
    except (OSError, ValueError):  # FileNotFoundError — подкласс OSError
        return None
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def record_issue(document: TechDocument, *, contact, session, ip: str) -> None:
    """Аудит выдачи: кто (контакт, сессия, IP), что (вид, номер, id документа и карточки) и когда (метка записи).

    Код события тот же, что у документов сделки (`document.downloaded_by_client`): подпись и лента уже есть у ERP и Платформы;
    отличает запись `source: catalog` и `entity_type: tech_document`.
    """
    from crm.models import ActivityLog

    ActivityLog.objects.create(
        action="Клиент скачал документ",
        event_code="document.downloaded_by_client",
        event_params={
            "document_id": document.pk,
            "kind": document.kind,
            "number": document.number,
            "product_id": document.product_id,
            "source": "catalog",
            "contact_id": contact.pk,
            "contact_name": contact.name,
            "session_id": session.pk,
            "ip": ip,
        },
        detail=f"{document.title}: {contact.name}",
        entity_type="tech_document",
        entity_id=document.pk,
        company_id=contact.company_id,
        contact_id=contact.pk,
    )
