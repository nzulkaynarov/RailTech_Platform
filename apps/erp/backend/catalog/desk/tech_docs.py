"""Документы товара и техдокументация (D2-3, CAT-CARD-1): реестр файлов с привязкой к позиции и проекту.

Вид документа — запись справочника `DocumentKind`; у документа номер, «кем выдан», «выдан», «действует до» (пусто — бессрочно) и
«видно клиенту» (по умолчанию — из вида). Эталоны: 1С:УТ «Сертификаты номенклатуры», GS1 GDSN certification module.

Загрузка — через проверки `core.validators` (расширение, тип содержимого, подпись файла, размер), хранение — приватный
бакет ERP (`TechDocument.file`), выдача — потоком через представление с проверкой прав (`catalog.desk.views_tech_docs`).
Просмотр в Платформе — PDF и изображения (`previewable`); остальное скачивается.
"""

import mimetypes
import os

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from sales.models import Deal

from catalog.desk.items import ItemError
from catalog.models import DocumentKind, Product, TechDocument
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
    queryset = TechDocument.objects.select_related(
        "product", "deal", "deal__company", "deal__stage", "uploaded_by", "source_supplier"
    )
    text = (params.get("q") or "").strip()
    if text:
        queryset = queryset.filter(
            Q(title__icontains=text) | Q(original_name__icontains=text) | Q(product__name__icontains=text)
        )
    kind = (params.get("kind") or "").strip()
    if kind:
        queryset = queryset.filter(kind=kind)
    if str(params.get("product", "")).isdigit():
        queryset = queryset.filter(product_id=int(params["product"]))
    if str(params.get("deal", "")).isdigit():
        queryset = queryset.filter(deal_id=int(params["deal"]))
    review = (params.get("review_state") or "").strip()
    if review in REVIEW_STATES:
        queryset = queryset.filter(review_state=review)
    return queryset.order_by("-created_at", "-id")


def is_expired(doc, today=None) -> bool:
    """Срок «действует до» прошёл (пусто — бессрочно, не истёк)."""
    return bool(doc.valid_until and doc.valid_until < (today or timezone.localdate()))


def kind_names() -> dict[str, str]:
    """Код вида -> название, одним запросом на ответ (виды выключенные тоже: документы на них остаются)."""
    return dict(DocumentKind.objects.values_list("code", "name"))


def doc_fields(doc, names: dict[str, str], today=None) -> dict:
    """Поля документа, общие для строки реестра и карточки товара."""
    return {
        "id": doc.pk,
        "kind": doc.kind,
        "kind_name": names.get(doc.kind, doc.kind),
        "title": doc.title,
        "number": doc.number,
        "issued_by": doc.issued_by,
        "issued_at": doc.issued_at,
        "valid_until": doc.valid_until,
        "is_expired": is_expired(doc, today),
        "client_visible": doc.client_visible,
        "original_name": doc.original_name,
        "size_bytes": doc.size_bytes,
        "previewable": is_previewable(doc),
        "review_state": doc.review_state,
        "partner": doc.source_supplier.name if doc.source_supplier_id else None,
    }


def doc_row(doc, names: dict[str, str] | None = None) -> dict:
    deal = doc.deal
    names = names if names is not None else kind_names()
    return {
        **doc_fields(doc, names),
        "content_type": doc.content_type,
        "product": {"id": doc.product_id, "name": doc.product.name, "sku": doc.product.sku} if doc.product_id else None,
        "deal": (
            {
                "id": deal.pk,
                "number": deal.number or "",
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


def _kind(code) -> DocumentKind:
    kind = DocumentKind.objects.filter(code=(code or "other"), is_active=True).first()
    if kind is None:
        raise ItemError("TECH_DOC_KIND_INVALID", "kind")
    return kind


def _date(value, field: str):
    if value in (None, ""):
        return None
    parsed = value if hasattr(value, "year") else parse_date(str(value))
    if parsed is None:
        raise ItemError("TECH_DOC_DATE_INVALID", field)
    return parsed


def _flag(value) -> bool:
    return value is True or str(value).strip().lower() in ("1", "true", "yes", "on")


def _check_range(issued_at, valid_until) -> None:
    if issued_at and valid_until and valid_until < issued_at:
        raise ItemError("TECH_DOC_VALIDITY_RANGE_INVALID", "valid_until")


def _passport(data: dict) -> dict:
    """Номер, орган, даты и видимость из тела запроса: только те ключи, что пришли."""
    out: dict = {}
    if "number" in data:
        out["number"] = (data["number"] or "").strip()[:100]
    if "issued_by" in data:
        out["issued_by"] = (data["issued_by"] or "").strip()[:255]
    if "issued_at" in data:
        out["issued_at"] = _date(data["issued_at"], "issued_at")
    if "valid_until" in data:
        out["valid_until"] = _date(data["valid_until"], "valid_until")
    if "client_visible" in data and data["client_visible"] not in (None, ""):
        out["client_visible"] = _flag(data["client_visible"])
    return out


def create_doc(file, data: dict, actor) -> TechDocument:
    kind = _kind(data.get("kind"))
    content_type = validate_upload(file)
    product = _product(data.get("product_id"))
    deal = _deal(data.get("deal_id"))
    if product is None and deal is None:
        raise ItemError("TECH_DOC_LINK_REQUIRED", "product_id")
    passport = _passport(data)
    _check_range(passport.get("issued_at"), passport.get("valid_until"))
    passport.setdefault("client_visible", kind.client_visible_default)
    title = (data.get("title") or "").strip() or os.path.splitext(file.name)[0]
    return TechDocument.objects.create(
        kind=kind.code,
        title=title[:255],
        file=file,
        original_name=os.path.basename(file.name)[:255],
        content_type=content_type,
        size_bytes=file.size,
        product=product,
        deal=deal,
        uploaded_by=actor,
        **passport,
    )


REVIEW_STATES = ("approved", "pending", "rejected")


def review_doc(doc: TechDocument, decision: str, actor, client_visible=None) -> TechDocument:
    """Решение сотрудника по документу партнёра: одобрить (клиенту виден по решению) или отклонить."""
    if doc.review_state != "pending":
        raise ItemError("TECH_DOC_NOT_PENDING", "review_state")
    if decision == "approve":
        doc.review_state = "approved"
        doc.client_visible = _kind_default(doc) if client_visible is None else bool(client_visible)
    else:
        doc.review_state = "rejected"
        doc.client_visible = False
    doc.reviewed_by = actor
    doc.reviewed_at = timezone.now()
    doc.save(update_fields=["review_state", "client_visible", "reviewed_by", "reviewed_at"])
    return doc


def _kind_default(doc: TechDocument) -> bool:
    kind = DocumentKind.objects.filter(code=doc.kind).first()
    return bool(kind and kind.client_visible_default)


def update_doc(doc: TechDocument, data: dict) -> TechDocument:
    """Правка паспорта документа: вид, название, номер, орган, даты, «видно клиенту». Файл не меняется."""
    # Активность вида проверяется только при смене: документ выключенного вида остаётся правимым (номер, срок, видимость).
    if "kind" in data and data["kind"] != doc.kind:
        doc.kind = _kind(data["kind"]).code
    if "title" in data:
        title = (data["title"] or "").strip()
        if title:
            doc.title = title[:255]
    for name, value in _passport(data).items():
        # Видимость клиенту решается только при одобрении: документ партнёра «на проверке» или отклонённый её не получает
        if name == "client_visible" and doc.review_state != "approved":
            continue
        setattr(doc, name, value)
    _check_range(doc.issued_at, doc.valid_until)
    doc.save()
    return doc


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
