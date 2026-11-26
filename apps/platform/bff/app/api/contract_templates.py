"""Документы · Шаблоны · Договоры (ДОК-10): список, новая редакция, «На утверждение», «Утвердить».

BFF не решает: статус, редакция, право утверждать (`contract.approve_template`, держатель зоны
«Право») и закреплённый текст — в ERP (`crm/document-templates`). Здесь — разделы каталога и
перевод ответа ERP в контракт.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.api.admin_company import _erp
from app.deps import Authed, require_any
from app.errors import PlatformError
from app.schemas_company import DocumentTemplate, to_document_template
from app.schemas_contract_templates import (
    ContractTemplate,
    ContractTemplateIn,
    ContractTemplateList,
    ContractTemplateRoleIn,
    OfferedContractTemplates,
    TemplateWordCheck,
    to_contract_template,
    to_offered,
    to_word_check,
)

router = APIRouter(tags=["templates"])

# Читают и готовят те, кто ведёт договоры и настройки; утверждает держатель «Право» (решает ERP).
Reader = Annotated[
    Authed,
    Depends(
        require_any(
            ("eds.projects", "read"), ("company.settings", "read"), ("eds.visa.legal", "read")
        )
    ),
]
Writer = Annotated[
    Authed,
    Depends(
        require_any(
            ("eds.projects", "full"), ("company.settings", "full"), ("eds.visa.legal", "full")
        )
    ),
]
Approver = Annotated[Authed, Depends(require_any(("eds.visa.legal", "full"), ("admin", "full")))]
ItemId = Annotated[str, Path(pattern=r"^[0-9]+$")]
BASE = "crm/document-templates"
Language = Annotated[Literal["ru", "uz", "en"], Query()]
#: Файл Word шаблона — до 5 МБ; тело читается потоком и обрывается за пределом
#: (сам файл проверяет ERP).
MAX_WORD_BYTES = 5 * 1024 * 1024
MAX_WORD_BODY = MAX_WORD_BYTES + 256 * 1024


@router.get(
    "/document-templates/contracts",
    response_model=ContractTemplateList,
    operation_id="listContractTemplates",
)
async def list_contract_templates(authed: Reader) -> ContractTemplateList:
    rows = await _erp(authed).data("GET", f"{BASE}/contracts/")
    return ContractTemplateList(items=[to_contract_template(r) for r in rows])


@router.post(
    "/document-templates/contracts",
    response_model=ContractTemplate,
    status_code=status.HTTP_201_CREATED,
    operation_id="createContractTemplate",
)
async def create_contract_template(body: ContractTemplateIn, authed: Writer) -> ContractTemplate:
    raw = await _erp(authed).data(
        "POST",
        f"{BASE}/create-contract/",
        json={
            "name": body.name,
            "counterparty_kind": body.counterparty,
            "subject": body.subject,
            **({"base_role": body.base_role} if body.base_role else {}),
        },
    )
    return to_contract_template(raw)


@router.patch(
    "/document-templates/contracts/{id}/base-role",
    response_model=ContractTemplate,
    operation_id="setContractTemplateBaseRole",
)
async def set_base_role(
    id: ItemId, body: ContractTemplateRoleIn, authed: Writer
) -> ContractTemplate:
    """Пометка «Базовый документ» в черновике; закреплённый текст и неверную роль отклоняет ERP."""
    raw = await _erp(authed).data(
        "PATCH", f"{BASE}/{id}/", json={"base_role": body.base_role or ""}
    )
    return to_contract_template(raw)


@router.get(
    "/document-templates/contracts/offered",
    response_model=OfferedContractTemplates,
    operation_id="listOfferedContractTemplates",
)
async def offered_contract_templates(
    authed: Reader, deal_id: Annotated[int, Query(ge=1)]
) -> OfferedContractTemplates:
    return to_offered(
        await _erp(authed).data("GET", f"{BASE}/offered/", params={"deal_id": deal_id})
    )


@router.post(
    "/document-templates/contracts/{id}/new-edition",
    response_model=ContractTemplate,
    status_code=status.HTTP_201_CREATED,
    operation_id="newContractTemplateEdition",
)
async def new_edition(id: ItemId, authed: Writer) -> ContractTemplate:
    return to_contract_template(await _erp(authed).data("POST", f"{BASE}/{id}/new-edition/"))


@router.post(
    "/document-templates/contracts/{id}/submit",
    response_model=ContractTemplate,
    operation_id="submitContractTemplate",
)
async def submit(id: ItemId, authed: Writer) -> ContractTemplate:
    return to_contract_template(await _erp(authed).data("POST", f"{BASE}/{id}/submit/"))


@router.post(
    "/document-templates/contracts/{id}/approve",
    response_model=ContractTemplate,
    operation_id="approveContractTemplate",
)
async def approve(id: ItemId, authed: Approver) -> ContractTemplate:
    return to_contract_template(await _erp(authed).data("POST", f"{BASE}/{id}/approve/"))


@router.post(
    "/document-templates/contracts/{id}/return-to-draft",
    response_model=ContractTemplate,
    operation_id="returnContractTemplateToDraft",
)
async def return_to_draft(id: ItemId, authed: Approver) -> ContractTemplate:
    return to_contract_template(await _erp(authed).data("POST", f"{BASE}/{id}/return-to-draft/"))


# --- ШАБЛ-1: Word ---------------------------------------------------------------------


def _word_too_large() -> PlatformError:
    return PlatformError(
        "PAYLOAD_TOO_LARGE",
        "Файл больше 5 МБ.",
        status_code=413,
        details={"max_bytes": MAX_WORD_BYTES},
    )


async def _word_body(request: Request) -> tuple[bytes, str]:
    """Тело загрузки целиком до предела; форма не разбирается (тип, архив и текст — ERP)."""
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Приложите файл к запросу.",
            status_code=422,
            details={"fields": ["file"], "reason": "multipart_required"},
        )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WORD_BODY:
        raise _word_too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WORD_BODY:
            raise _word_too_large()
    return bytes(body), content_type


@router.get(
    "/document-templates/{id}/word",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}
            }
        }
    },
    operation_id="downloadTemplateWord",
)
async def download_word(id: ItemId, language: Language, authed: Reader) -> Response:
    response = await _erp(authed).request(
        "GET", f"{BASE}/{id}/word/", params={"language": language}
    )
    given = response.headers.get("content-disposition", "")
    disposition = given if given.startswith("attachment;") else "attachment"
    return Response(
        content=response.content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/document-templates/{id}/word/check",
    response_model=TemplateWordCheck,
    operation_id="checkTemplateWord",
)
async def check_word(
    id: ItemId, language: Language, request: Request, authed: Writer
) -> TemplateWordCheck:
    content, content_type = await _word_body(request)
    response = await _erp(authed).request(
        "POST",
        f"{BASE}/{id}/word/",
        params={"language": language, "mode": "check"},
        content=content,
        content_type=content_type,
    )
    return to_word_check(response.json())


@router.post(
    "/document-templates/{id}/word/apply",
    response_model=DocumentTemplate,
    operation_id="applyTemplateWord",
)
async def apply_word(
    id: ItemId,
    language: Language,
    request: Request,
    authed: Writer,
    base: Annotated[str, Query(pattern=r"^[0-9a-f]{16}$")],
    file_sha: Annotated[str, Query(pattern=r"^[0-9a-f]{16}$")],
) -> DocumentTemplate:
    content, content_type = await _word_body(request)
    response = await _erp(authed).request(
        "POST",
        f"{BASE}/{id}/word/",
        params={
            "language": language,
            "mode": "apply",
            "base": base,
            "file_sha": file_sha,
        },
        content=content,
        content_type=content_type,
    )
    return to_document_template(response.json())
