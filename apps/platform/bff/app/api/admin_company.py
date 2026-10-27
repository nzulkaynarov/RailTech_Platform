"""Admin · Компания: реквизиты, бланк и бренд, нумерация, условия КП, статьи расхода, шаблоны,
справочники, категории, платформенные настройки и курс USD→UZS своей компании в ERP (контракт 0.8.0,
0.13.0, tag `admin`).

BFF не решает: данные и права на операции — в ERP (`settings.edit`, `settings.charge_templates`,
администратор платформы для решений по запросам на категории и ставки НДС). BFF проверяет раздел
каталога `company.settings` (чтение — `GET` и предпросмотры, полный — изменения), находит id своей
компании по профилю сотрудника в ERP и вырезает поля маржи без права на группу `cost_margin`.
Логотипы передаются в ERP как есть (`multipart/form-data`, до 2 МБ).
"""

import re
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.clients.erp_company import ErpCompany
from app.deps import Authed, require
from app.errors import PlatformError
from app.schemas_company import (
    COST_MARGIN_GROUP,
    KIND_TO_ERP,
    MARGIN_FIELDS,
    REFERENCE_PATH,
    TEMPLATE_KIND_TO_ERP,
    BrandPreviewIn,
    BrandProfile,
    BrandProfileUpdate,
    CatalogCategory,
    CatalogCategoryIn,
    CatalogCategoryList,
    CatalogCategoryUpdate,
    CategoryRequest,
    CategoryRequestApproveIn,
    CategoryRequestList,
    CategoryRequestRejectIn,
    ChargeTemplate,
    ChargeTemplateIn,
    ChargeTemplateList,
    ChargeTemplateUpdate,
    ChargeTypeList,
    CompanyProfile,
    CompanyProfileUpdate,
    DocumentPlaceholders,
    DocumentPreview,
    DocumentTemplate,
    DocumentTemplateCopyIn,
    DocumentTemplateIn,
    DocumentTemplateList,
    DocumentTemplatePreviewIn,
    DocumentTemplateUpdate,
    EmailTemplate,
    EmailTemplateIn,
    EmailTemplateList,
    EmailTemplatePreview,
    EmailTemplateUpdate,
    FxRateIn,
    FxRateOverview,
    NumberingPreview,
    NumberingPreviewIn,
    NumberingScheme,
    NumberingUpdate,
    PlatformSettings,
    PlatformSettingsUpdate,
    QuoteDefaults,
    QuoteDefaultsUpdate,
    ReferenceItem,
    ReferenceItemIn,
    ReferenceItemList,
    ReferenceItemUpdate,
    ReferenceKind,
    RequestStatus,
    foreign_reference_fields,
    labels_to_erp,
    text,
    to_brand,
    to_category,
    to_category_request,
    to_charge_template,
    to_charge_type,
    to_company,
    to_document_template,
    to_email_template,
    to_fx_overview,
    to_numbering,
    to_numbering_preview,
    to_placeholders,
    to_platform_settings,
    to_quote_defaults,
    to_reference_item,
)

router = APIRouter(tags=["admin"])

Reader = Annotated[Authed, Depends(require("company.settings", "read"))]
Writer = Annotated[Authed, Depends(require("company.settings", "full"))]
ItemId = Annotated[str, Path(pattern=r"^[0-9]+$")]
Kind = Annotated[ReferenceKind, Path()]

MAX_LOGO_BYTES = 2 * 1024 * 1024
LOGO_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/svg+xml"})
# Заголовки части `logo` multipart: тип файла, который назвал браузер (содержимое проверяет ERP).
_LOGO_PART = re.compile(
    rb'content-disposition:[^\r\n]*name="logo"[^\r\n]*\r\n'
    rb"(?:[^\r\n]+\r\n)*?content-type:[ \t]*([^\r\n;]+)",
    re.IGNORECASE,
)
_PART_HEADERS_WINDOW = 4096
_MULTIPART_OVERHEAD = 64 * 1024  # границы и заголовки частей поверх файла


def _erp(authed: Authed) -> ErpCompany:
    return ErpCompany(authed.call)


def _bad_logo(reason: str) -> PlatformError:
    return PlatformError(
        "VALIDATION_FAILED",
        "Загрузите файл логотипа (PNG, JPEG, WebP или SVG) не больше 2 МБ.",
        status_code=422,
        details={"fields": ["logo"], "reason": reason},
    )


async def _multipart(request: Request) -> tuple[bytes, str]:
    """Тело загрузки логотипа целиком: BFF его не разбирает, а передаёт ERP."""
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise _bad_logo("multipart_required")
    limit = MAX_LOGO_BYTES + _MULTIPART_OVERHEAD
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _bad_logo("file_too_large")
    body = await request.body()
    if len(body) > limit:
        raise _bad_logo("file_too_large")
    # Тип части `logo` — из её заголовков (начало тела); иначе ERP не вызывается.
    found = _LOGO_PART.search(body[:_PART_HEADERS_WINDOW])
    mime = found.group(1).strip().lower().decode("ascii", "ignore") if found else ""
    if mime not in LOGO_TYPES:
        raise _bad_logo("unsupported_type")
    return body, content_type


def _ids_to_erp(sent: dict[str, Any]) -> dict[str, Any]:
    """`parent_id` строкой -> `parent` числом ERP."""
    out = dict(sent)
    if "parent_id" in out:
        parent = out.pop("parent_id")
        out["parent"] = int(parent) if parent is not None else None
    return out


# --- реквизиты и логотип -----------------------------------------------------------------------


@router.get("/admin/company", response_model=CompanyProfile, operation_id="getCompany")
async def get_company(authed: Reader) -> CompanyProfile:
    erp = _erp(authed)
    return to_company(await erp.data("GET", await erp.company_path()))


@router.patch("/admin/company", response_model=CompanyProfile, operation_id="updateCompany")
async def update_company(body: CompanyProfileUpdate, authed: Writer) -> CompanyProfile:
    erp = _erp(authed)
    return to_company(await erp.data("PATCH", await erp.company_path(), json=body.sent()))


@router.post("/admin/company/logo", response_model=CompanyProfile, operation_id="uploadCompanyLogo")
async def upload_company_logo(request: Request, authed: Writer) -> CompanyProfile:
    content, content_type = await _multipart(request)
    erp = _erp(authed)
    response = await erp.request(
        "POST", await erp.company_path("upload-logo/"), content=content, content_type=content_type
    )
    return to_company(response.json())


def _logo_image(file: httpx.Response | None) -> Response:
    """Файл логотипа как есть и с защитными заголовками ERP (SVG не исполняет скрипты)."""
    if file is None:
        raise PlatformError("NOT_FOUND", "Логотипа нет.", status_code=404)
    return Response(
        content=file.content,
        media_type=file.headers["content-type"].split(";")[0].strip(),
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )


@router.get(
    "/admin/company/logo/image", response_class=Response, operation_id="getCompanyLogoImage"
)
async def get_company_logo_image(authed: Reader) -> Response:
    erp = _erp(authed)
    raw = await erp.data("GET", await erp.company_path())
    return _logo_image(await erp.media(raw.get("logo")))


@router.delete(
    "/admin/company/logo", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteCompanyLogo"
)
async def delete_company_logo(authed: Writer) -> Response:
    erp = _erp(authed)
    await erp.request("DELETE", await erp.company_path("delete-logo/"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- бланк и бренд -----------------------------------------------------------------------------


@router.get("/admin/company/brand", response_model=BrandProfile, operation_id="getBrandProfile")
async def get_brand_profile(authed: Reader) -> BrandProfile:
    erp = _erp(authed)
    return to_brand(await erp.data("GET", await erp.company_path("document-profile/")))


@router.patch(
    "/admin/company/brand", response_model=BrandProfile, operation_id="updateBrandProfile"
)
async def update_brand_profile(body: BrandProfileUpdate, authed: Writer) -> BrandProfile:
    erp = _erp(authed)
    path = await erp.company_path("document-profile/")
    return to_brand(await erp.data("PATCH", path, json=body.sent()))


@router.post(
    "/admin/company/brand/logo", response_model=BrandProfile, operation_id="uploadBrandLogo"
)
async def upload_brand_logo(request: Request, authed: Writer) -> BrandProfile:
    content, content_type = await _multipart(request)
    erp = _erp(authed)
    response = await erp.request(
        "POST",
        await erp.company_path("document-profile/upload-logo/"),
        content=content,
        content_type=content_type,
    )
    return to_brand(response.json())


@router.get(
    "/admin/company/brand/logo/image", response_class=Response, operation_id="getBrandLogoImage"
)
async def get_brand_logo_image(authed: Reader) -> Response:
    erp = _erp(authed)
    raw = await erp.data("GET", await erp.company_path("document-profile/"))
    return _logo_image(await erp.media(raw.get("logo_url") or raw.get("logo")))


@router.post(
    "/admin/company/brand/preview",
    response_model=DocumentPreview,
    response_model_exclude_none=True,
    operation_id="previewBrandDocument",
)
async def preview_brand_document(body: BrandPreviewIn, authed: Reader) -> DocumentPreview:
    erp = _erp(authed)
    payload: dict[str, Any] = {"doc_type": KIND_TO_ERP[body.kind]}
    if body.draft is not None:
        payload["draft"] = body.draft.sent()
    response = await erp.request(
        "POST", await erp.company_path("document-profile/preview/"), json=payload
    )
    return DocumentPreview(html=await erp.inline_logos(response.text))


# --- нумерация ---------------------------------------------------------------------------------


@router.get(
    "/admin/company/numbering", response_model=NumberingScheme, operation_id="getNumberingScheme"
)
async def get_numbering(authed: Reader) -> NumberingScheme:
    return to_numbering(await _erp(authed).data("GET", "crm/numbering-scheme/"))


@router.patch(
    "/admin/company/numbering", response_model=NumberingScheme, operation_id="updateNumberingScheme"
)
async def update_numbering(body: NumberingUpdate, authed: Writer) -> NumberingScheme:
    erp = _erp(authed)
    sent = body.sent()
    prefix = sent.pop("prefix", None)
    if prefix is not None:
        # Префикс — настройка компании в ERP (`doc_number_prefix`): с ним схема действует.
        await erp.data(
            "PATCH",
            await erp.company_path("settings/"),
            json={"doc_number_prefix": prefix.strip()},
        )
    if "type_labels" in sent:
        sent["type_labels"] = labels_to_erp(sent["type_labels"])
    scheme = await erp.data("PATCH", "crm/numbering-scheme/", json=sent) if sent else None
    if scheme is None:
        scheme = await erp.data("GET", "crm/numbering-scheme/")
    return to_numbering(scheme)


@router.post(
    "/admin/company/numbering/preview",
    response_model=NumberingPreview,
    operation_id="previewNumbering",
)
async def preview_numbering(body: NumberingPreviewIn, authed: Reader) -> NumberingPreview:
    payload = body.model_dump(exclude_none=True)
    if "type_labels" in payload:
        payload["type_labels"] = labels_to_erp(payload["type_labels"])
    data = await _erp(authed).data("POST", "crm/numbering-scheme/preview/", json=payload)
    return to_numbering_preview(data)


# --- условия КП --------------------------------------------------------------------------------


@router.get(
    "/admin/company/quote-defaults",
    response_model=QuoteDefaults,
    response_model_exclude_unset=True,
    operation_id="getQuoteDefaults",
)
async def get_quote_defaults(authed: Reader) -> QuoteDefaults:
    erp = _erp(authed)
    raw = await erp.data("GET", await erp.company_path("settings/"))
    return to_quote_defaults(raw, authed.fields)


@router.patch(
    "/admin/company/quote-defaults",
    response_model=QuoteDefaults,
    response_model_exclude_unset=True,
    operation_id="updateQuoteDefaults",
)
async def update_quote_defaults(body: QuoteDefaultsUpdate, authed: Writer) -> QuoteDefaults:
    sent = body.sent()
    blocked = [name for name in MARGIN_FIELDS if name in sent]
    if blocked and COST_MARGIN_GROUP not in authed.fields:
        raise PlatformError(
            "FORBIDDEN",
            "Маржу в условиях КП меняют роли с правом видеть себестоимость и маржу.",
            status_code=403,
            details={
                "resource": "company.settings",
                "restricted": COST_MARGIN_GROUP,
                "fields": blocked,
            },
        )
    erp = _erp(authed)
    raw = await erp.data("PATCH", await erp.company_path("settings/"), json=sent)
    return to_quote_defaults(raw, authed.fields)


# --- статьи расхода ----------------------------------------------------------------------------


@router.get(
    "/admin/company/charge-types", response_model=ChargeTypeList, operation_id="listChargeTypes"
)
async def list_charge_types(authed: Reader) -> ChargeTypeList:
    rows = await _erp(authed).pages("crm/charge-types/")
    return ChargeTypeList(items=[to_charge_type(r) for r in rows])


@router.get(
    "/admin/company/charge-templates",
    response_model=ChargeTemplateList,
    operation_id="listChargeTemplates",
)
async def list_charge_templates(authed: Reader) -> ChargeTemplateList:
    rows = await _erp(authed).pages("crm/charge-templates/")
    return ChargeTemplateList(items=[to_charge_template(r) for r in rows])


@router.post(
    "/admin/company/charge-templates",
    response_model=ChargeTemplate,
    status_code=status.HTTP_201_CREATED,
    operation_id="createChargeTemplate",
)
async def create_charge_template(body: ChargeTemplateIn, authed: Writer) -> ChargeTemplate:
    raw = await _erp(authed).data("POST", "crm/charge-templates/", json=body.sent())
    return to_charge_template(raw)


@router.patch(
    "/admin/company/charge-templates/{id}",
    response_model=ChargeTemplate,
    operation_id="updateChargeTemplate",
)
async def update_charge_template(
    id: ItemId, body: ChargeTemplateUpdate, authed: Writer
) -> ChargeTemplate:
    raw = await _erp(authed).data("PATCH", f"crm/charge-templates/{id}/", json=body.sent())
    return to_charge_template(raw)


@router.delete(
    "/admin/company/charge-templates/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteChargeTemplate",
)
async def delete_charge_template(id: ItemId, authed: Writer) -> Response:
    await _erp(authed).request("DELETE", f"crm/charge-templates/{id}/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- шаблоны документов ------------------------------------------------------------------------


@router.get(
    "/admin/company/document-templates",
    response_model=DocumentTemplateList,
    operation_id="listDocumentTemplates",
)
async def list_document_templates(authed: Reader) -> DocumentTemplateList:
    rows = await _erp(authed).pages("crm/document-templates/")
    return DocumentTemplateList(items=[to_document_template(r) for r in rows])


@router.post(
    "/admin/company/document-templates",
    response_model=DocumentTemplate,
    status_code=status.HTTP_201_CREATED,
    operation_id="createDocumentTemplate",
)
async def create_document_template(body: DocumentTemplateIn, authed: Writer) -> DocumentTemplate:
    raw = await _erp(authed).data("POST", "crm/document-templates/", json=body.sent())
    return to_document_template(raw)


@router.get(
    "/admin/company/document-templates/placeholders",
    response_model=DocumentPlaceholders,
    operation_id="getDocumentPlaceholders",
)
async def get_document_placeholders(authed: Reader) -> DocumentPlaceholders:
    return to_placeholders(await _erp(authed).data("GET", "crm/document-templates/placeholders/"))


@router.post(
    "/admin/company/document-templates/preview",
    response_model=DocumentPreview,
    response_model_exclude_none=True,
    operation_id="previewDocumentTemplate",
)
async def preview_document_template(
    body: DocumentTemplatePreviewIn, authed: Reader
) -> DocumentPreview:
    raw = await _erp(authed).data(
        "POST",
        "crm/document-templates/preview/",
        json={
            "body_html": body.body_html,
            **({"kind": TEMPLATE_KIND_TO_ERP[body.kind]} if body.kind else {}),
        },
    )
    warnings = [text(w) for w in raw.get("warnings") or []]
    erp = _erp(authed)
    html = await erp.inline_logos(text(raw.get("document_html")) or text(raw.get("rendered_html")))
    return DocumentPreview(html=html, warnings=warnings or None)


@router.patch(
    "/admin/company/document-templates/{id}",
    response_model=DocumentTemplate,
    operation_id="updateDocumentTemplate",
)
async def update_document_template(
    id: ItemId, body: DocumentTemplateUpdate, authed: Writer
) -> DocumentTemplate:
    raw = await _erp(authed).data("PATCH", f"crm/document-templates/{id}/", json=body.sent())
    return to_document_template(raw)


@router.delete(
    "/admin/company/document-templates/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteDocumentTemplate",
)
async def delete_document_template(id: ItemId, authed: Writer) -> Response:
    await _erp(authed).request("DELETE", f"crm/document-templates/{id}/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/admin/company/document-templates/{id}/copy",
    response_model=DocumentTemplate,
    operation_id="copyDocumentTemplate",
)
async def copy_document_template(
    id: ItemId, body: DocumentTemplateCopyIn, authed: Writer
) -> DocumentTemplate:
    raw = await _erp(authed).data(
        "POST", f"crm/document-templates/{id}/copy/", json={"name": body.name}
    )
    return to_document_template(raw)


# --- шаблоны писем -----------------------------------------------------------------------------


@router.get(
    "/admin/company/email-templates",
    response_model=EmailTemplateList,
    response_model_exclude_unset=True,
    operation_id="listEmailTemplates",
)
async def list_email_templates(authed: Reader) -> EmailTemplateList:
    rows = await _erp(authed).pages("settings/email-templates/")
    return EmailTemplateList(items=[to_email_template(r) for r in rows])


@router.post(
    "/admin/company/email-templates",
    response_model=EmailTemplate,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
    operation_id="createEmailTemplate",
)
async def create_email_template(body: EmailTemplateIn, authed: Writer) -> EmailTemplate:
    raw = await _erp(authed).data(
        "POST", "settings/email-templates/", json=body.model_dump(exclude_none=True)
    )
    return to_email_template(raw)


@router.patch(
    "/admin/company/email-templates/{id}",
    response_model=EmailTemplate,
    response_model_exclude_unset=True,
    operation_id="updateEmailTemplate",
)
async def update_email_template(
    id: ItemId, body: EmailTemplateUpdate, authed: Writer
) -> EmailTemplate:
    raw = await _erp(authed).data("PATCH", f"settings/email-templates/{id}/", json=body.sent())
    return to_email_template(raw)


@router.delete(
    "/admin/company/email-templates/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteEmailTemplate",
)
async def delete_email_template(id: ItemId, authed: Writer) -> Response:
    await _erp(authed).request("DELETE", f"settings/email-templates/{id}/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/admin/company/email-templates/{id}/preview",
    response_model=EmailTemplatePreview,
    operation_id="previewEmailTemplate",
)
async def preview_email_template(id: ItemId, authed: Reader) -> EmailTemplatePreview:
    raw = await _erp(authed).data("POST", f"settings/email-templates/{id}/preview/", json={})
    return EmailTemplatePreview(
        subject=text(raw.get("subject")),
        text_body=text(raw.get("text_body")),
        html_body=text(raw.get("html_body")),
    )


# --- справочники -------------------------------------------------------------------------------


def _reference_payload(kind: str, sent: dict[str, Any]) -> dict[str, Any]:
    foreign = foreign_reference_fields(kind, sent)
    if foreign:
        raise PlatformError(
            "VALIDATION_FAILED",
            "Проверьте заполнение полей.",
            status_code=422,
            details={"fields": foreign, "reason": "field_not_in_reference"},
        )
    return sent


@router.get(
    "/admin/company/reference/{kind}",
    response_model=ReferenceItemList,
    response_model_exclude_unset=True,
    operation_id="listReferenceItems",
)
async def list_reference_items(kind: Kind, authed: Reader) -> ReferenceItemList:
    rows = await _erp(authed).pages(REFERENCE_PATH[kind], {"include_inactive": "1"})
    return ReferenceItemList(items=[to_reference_item(kind, r) for r in rows])


@router.post(
    "/admin/company/reference/{kind}",
    response_model=ReferenceItem,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
    operation_id="createReferenceItem",
)
async def create_reference_item(kind: Kind, body: ReferenceItemIn, authed: Writer) -> ReferenceItem:
    payload = _reference_payload(kind, {k: v for k, v in body.sent().items() if v is not None})
    raw = await _erp(authed).data("POST", REFERENCE_PATH[kind], json=payload)
    return to_reference_item(kind, raw)


@router.patch(
    "/admin/company/reference/{kind}/{id}",
    response_model=ReferenceItem,
    response_model_exclude_unset=True,
    operation_id="updateReferenceItem",
)
async def update_reference_item(
    kind: Kind, id: ItemId, body: ReferenceItemUpdate, authed: Writer
) -> ReferenceItem:
    payload = _reference_payload(kind, body.sent())
    raw = await _erp(authed).data("PATCH", f"{REFERENCE_PATH[kind]}{id}/", json=payload)
    return to_reference_item(kind, raw)


@router.delete(
    "/admin/company/reference/{kind}/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteReferenceItem",
)
async def delete_reference_item(kind: Kind, id: ItemId, authed: Writer) -> Response:
    await _erp(authed).request("DELETE", f"{REFERENCE_PATH[kind]}{id}/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- категории каталога и запросы на них -------------------------------------------------------


@router.get(
    "/admin/company/categories",
    response_model=CatalogCategoryList,
    operation_id="listCatalogCategories",
)
async def list_categories(authed: Reader) -> CatalogCategoryList:
    rows = await _erp(authed).pages("catalog/categories/")
    return CatalogCategoryList(items=[to_category(r) for r in rows])


@router.post(
    "/admin/company/categories",
    response_model=CatalogCategory,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCatalogCategory",
)
async def create_category(body: CatalogCategoryIn, authed: Writer) -> CatalogCategory:
    raw = await _erp(authed).data(
        "POST", "catalog/categories/", json=_ids_to_erp(body.model_dump())
    )
    return to_category(raw)


@router.patch(
    "/admin/company/categories/{id}",
    response_model=CatalogCategory,
    operation_id="updateCatalogCategory",
)
async def update_category(
    id: ItemId, body: CatalogCategoryUpdate, authed: Writer
) -> CatalogCategory:
    raw = await _erp(authed).data(
        "PATCH", f"catalog/categories/{id}/", json=_ids_to_erp(body.sent())
    )
    return to_category(raw)


@router.delete(
    "/admin/company/categories/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCatalogCategory",
)
async def delete_category(id: ItemId, authed: Writer) -> Response:
    await _erp(authed).request("DELETE", f"catalog/categories/{id}/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/admin/company/category-requests",
    response_model=CategoryRequestList,
    response_model_exclude_unset=True,
    operation_id="listCategoryRequests",
)
async def list_category_requests(
    authed: Reader, status_filter: Annotated[RequestStatus | None, Query(alias="status")] = None
) -> CategoryRequestList:
    params = {"status": status_filter.upper()} if status_filter else None
    rows = await _erp(authed).pages("catalog/category-requests/", params)
    return CategoryRequestList(items=[to_category_request(r) for r in rows])


@router.post(
    "/admin/company/category-requests/{id}/approve",
    response_model=CategoryRequest,
    response_model_exclude_unset=True,
    operation_id="approveCategoryRequest",
)
async def approve_category_request(
    id: ItemId, body: CategoryRequestApproveIn, authed: Writer
) -> CategoryRequest:
    raw = await _erp(authed).data(
        "POST", f"catalog/category-requests/{id}/approve/", json={"category": int(body.category_id)}
    )
    return to_category_request(raw)


@router.post(
    "/admin/company/category-requests/{id}/reject",
    response_model=CategoryRequest,
    response_model_exclude_unset=True,
    operation_id="rejectCategoryRequest",
)
async def reject_category_request(
    id: ItemId, body: CategoryRequestRejectIn, authed: Writer
) -> CategoryRequest:
    raw = await _erp(authed).data(
        "POST", f"catalog/category-requests/{id}/reject/", json={"reason": body.reason.strip()}
    )
    return to_category_request(raw)


# --- платформенные настройки -------------------------------------------------------------------


@router.get(
    "/admin/company/platform-settings",
    response_model=PlatformSettings,
    operation_id="getPlatformSettings",
)
async def get_platform_settings(authed: Reader) -> PlatformSettings:
    return to_platform_settings(await _erp(authed).data("GET", "system-settings/"))


@router.patch(
    "/admin/company/platform-settings",
    response_model=PlatformSettings,
    operation_id="updatePlatformSettings",
)
async def update_platform_settings(
    body: PlatformSettingsUpdate, authed: Writer
) -> PlatformSettings:
    raw = await _erp(authed).data("PATCH", "system-settings/", json=body.sent())
    return to_platform_settings(raw)


# --- курс USD→UZS: ручной ввод и журнал (W13C-F6) ----------------------------------------------

FX_JOURNAL_LIMIT = 20


async def _fx_overview(erp: ErpCompany) -> FxRateOverview:
    current = await erp.data("GET", "exchange-rates/current/", params={"currency": "USD"})
    journal: Any = []
    available = True
    try:
        journal = await erp.data(
            "GET", "exchange-rates/journal/", params={"currency": "USD", "limit": FX_JOURNAL_LIMIT}
        )
    except PlatformError as error:
        # Журнал с именами и почтой коллег ERP отдаёт только с `settings.edit` (W15-H8).
        # Директор читает раздел «Компания» без этого права: курс виден, журнала нет.
        if error.status_code != 403:
            raise
        available = False
    return to_fx_overview(
        current if isinstance(current, dict) else {},
        [row for row in journal if isinstance(row, dict)] if isinstance(journal, list) else [],
        journal_available=available,
    )


@router.get("/admin/company/fx-rate", response_model=FxRateOverview, operation_id="getFxRate")
async def get_fx_rate(authed: Reader) -> FxRateOverview:
    return await _fx_overview(_erp(authed))


@router.post(
    "/admin/company/fx-rate",
    response_model=FxRateOverview,
    status_code=status.HTTP_201_CREATED,
    operation_id="createFxRate",
)
async def create_fx_rate(body: FxRateIn, authed: Writer) -> FxRateOverview:
    erp = _erp(authed)
    await erp.request("POST", "exchange-rates/manual/", json=body.to_erp())
    return await _fx_overview(erp)
