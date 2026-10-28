"""Техдокументация (D2-3): реестр файлов ТЗ, чертежей, сертификатов и регламентов ПНР с привязкой к позиции и проекту.

Загрузка — через проверки `core.validators` (расширение, тип содержимого, подпись файла, размер), хранение — приватный
бакет ERP (`TechDocument.file`), выдача — потоком через представление с проверкой прав (`catalog.desk.views_tech_docs`).
Просмотр в Платформе — PDF и изображения (`previewable`); остальное скачивается.
"""

import mimetypes
import os

from django.core.exceptions import ValidationError
from django.db.models import Q
from sales.models import Deal

from catalog.desk.items import ItemError
from catalog.models import Product, TechDocument
from core.validators import _validate_file

#: Разрешённые форматы: документы Office, PDF и растровые изображения (чертёж скриншотом/сканом).
TECH_DOC_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".xls", ".xlsx"}
TECH_DOC_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
TECH_DOC_MAX_SIZE = 20 * 1024 * 1024  # 20 МБ
PREVIEW_TYPES = {"application/pdf", "image/png", "image/jpeg"}


def is_previewable(doc) -> bool:
    return doc.content_type in PREVIEW_TYPES


def guess_content_type(name: str, declared: str | None = None) -> str:
    return mimetypes.guess_type(name)[0] or declared or "application/octet-stream"


def validate_upload(file) -> str:
    """Проверка файла; возвращает тип содержимого по расширению. Ошибка — `ItemError` с кодом ответа."""
    try:
        _validate_file(file, TECH_DOC_EXTENSIONS, TECH_DOC_CONTENT_TYPES, TECH_DOC_MAX_SIZE, label="Tech document")
    except ValidationError as error:
        message = " ".join(error.messages)
        if "exceeds" in message:
            raise ItemError("FILE_TOO_LARGE", "file") from None
        if "does not match" in message:
            raise ItemError("FILE_CONTENT_MISMATCH", "file") from None
        raise ItemError("FILE_TYPE_NOT_ALLOWED", "file") from None
    return guess_content_type(file.name, getattr(file, "content_type", None))


def list_queryset(params):
    queryset = TechDocument.objects.select_related("product", "deal", "deal__company", "deal__stage", "uploaded_by")
    text = (params.get("q") or "").strip()
    if text:
        queryset = queryset.filter(
            Q(title__icontains=text) | Q(original_name__icontains=text) | Q(product__name__icontains=text)
        )
    if params.get("kind") in TechDocument.Kind.values:
        queryset = queryset.filter(kind=params["kind"])
    if str(params.get("product", "")).isdigit():
        queryset = queryset.filter(product_id=int(params["product"]))
    if str(params.get("deal", "")).isdigit():
        queryset = queryset.filter(deal_id=int(params["deal"]))
    return queryset.order_by("-created_at", "-id")


def doc_row(doc) -> dict:
    deal = doc.deal
    return {
        "id": doc.pk,
        "kind": doc.kind,
        "title": doc.title,
        "original_name": doc.original_name,
        "content_type": doc.content_type,
        "size_bytes": doc.size_bytes,
        "previewable": is_previewable(doc),
        "product": {"id": doc.product_id, "name": doc.product.name, "sku": doc.product.sku} if doc.product_id else None,
        "deal": (
            {
                "id": deal.pk,
                "title": deal.title or "",
                "client": _client_name(deal),
                "stage_code": deal.stage.code if deal.stage_id else "",
                "created_at": deal.created_at,
            }
            if deal
            else None
        ),
        "uploaded_by": (doc.uploaded_by.get_full_name() or doc.uploaded_by.email) if doc.uploaded_by_id else None,
        "created_at": doc.created_at,
    }


def _client_name(deal) -> str:
    return deal.company.name if deal.company_id else ""


def create_doc(file, data: dict, actor) -> TechDocument:
    kind = data.get("kind") or TechDocument.Kind.OTHER
    if kind not in TechDocument.Kind.values:
        raise ItemError("TECH_DOC_KIND_INVALID", "kind")
    content_type = validate_upload(file)
    product = _product(data.get("product_id"))
    deal = _deal(data.get("deal_id"))
    if product is None and deal is None:
        raise ItemError("TECH_DOC_LINK_REQUIRED", "product_id")
    title = (data.get("title") or "").strip() or os.path.splitext(file.name)[0]
    return TechDocument.objects.create(
        kind=kind,
        title=title[:255],
        file=file,
        original_name=os.path.basename(file.name)[:255],
        content_type=content_type,
        size_bytes=file.size,
        product=product,
        deal=deal,
        uploaded_by=actor,
    )


def _product(value):
    if value in (None, ""):
        return None
    if not str(value).isdigit():
        raise ItemError("PRODUCT_NOT_FOUND", "product_id")
    product = Product.objects.filter(pk=int(value)).exclude(status__code="ARCHIVED").first()
    if product is None:
        raise ItemError("PRODUCT_NOT_FOUND", "product_id")
    return product


def _deal(value):
    if value in (None, ""):
        return None
    if not str(value).isdigit():
        raise ItemError("DEAL_NOT_FOUND", "deal_id")
    deal = Deal.objects.select_related("company", "stage").filter(pk=int(value)).first()
    if deal is None:
        raise ItemError("DEAL_NOT_FOUND", "deal_id")
    return deal
