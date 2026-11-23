"""Шаблоны писем и служебок EDS (TPL-4, план 3.6): прокси к EDS `/templates` и `/template-previews`.

Читают все, кто создаёт документы (`eds.memo.create`), делопроизводитель и администратор;
правят делопроизводитель (`eds.inbox.register` полный) и администратор. Право на каждый вызов
решает EDS по своим кодам."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.eds_documents import FileStream
from app.deps import Authed, require_any
from app.eds_documents import EdsProxy, eds_error
from app.schemas_eds_documents import EdsDocumentBody

router = APIRouter(tags=["eds-documents"])
API = "/api/v1"

Reader = Annotated[
    Authed,
    Depends(
        require_any(("eds.memo.create", "read"), ("eds.inbox.register", "full"), ("admin", "read"))
    ),
]
Editor = Annotated[Authed, Depends(require_any(("eds.inbox.register", "full"), ("admin", "full")))]
TemplateId = Annotated[uuid.UUID, Path()]
PreviewId = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
Kind = Literal["letter", "memo"]
Lang = Literal["ru", "uz", "en"]


class EdsTemplateVariants(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ru: EdsDocumentBody | None = None
    uz: EdsDocumentBody | None = None
    en: EdsDocumentBody | None = None


class EdsTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    name: str = Field(min_length=1, max_length=120)
    variants: EdsTemplateVariants
    is_default: bool = False
    active: bool = True


class EdsTemplate(BaseModel):
    id: str
    kind: Kind
    name: str
    variants: dict[Lang, dict[str, Any]]
    languages: list[Lang]
    is_default: bool
    active: bool
    origin: Literal["builtin", "custom"]
    changed: bool
    updated_at: str


class EdsTemplateList(BaseModel):
    items: list[EdsTemplate]


class EdsTemplatePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: EdsDocumentBody
    kind: Kind = "letter"


class EdsTemplatePreview(BaseModel):
    hash: str
    status: Literal["pending", "ready", "failed"]
    error: str | None
    pages: int | None


def _proxy(authed: Authed) -> EdsProxy:
    return EdsProxy(authed.call)


def _in(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(mode="json", exclude_none=True)


@router.get("/eds/templates", response_model=EdsTemplateList, operation_id="listEdsTemplates")
async def list_templates(
    authed: Reader, kind: Annotated[Kind | None, Query()] = None
) -> EdsTemplateList:
    raw = await _proxy(authed).request(
        "GET", f"{API}/templates", params={"kind": kind} if kind else None
    )
    return EdsTemplateList.model_validate(raw)


@router.post(
    "/eds/templates",
    response_model=EdsTemplate,
    status_code=status.HTTP_201_CREATED,
    operation_id="createEdsTemplate",
)
async def create_template(body: EdsTemplateIn, authed: Editor) -> EdsTemplate:
    raw = await _proxy(authed).request("POST", f"{API}/templates", json=_in(body), expected=201)
    return EdsTemplate.model_validate(raw)


@router.get("/eds/templates/{id}", response_model=EdsTemplate, operation_id="getEdsTemplate")
async def get_template(id: TemplateId, authed: Reader) -> EdsTemplate:
    return EdsTemplate.model_validate(await _proxy(authed).request("GET", f"{API}/templates/{id}"))


@router.put("/eds/templates/{id}", response_model=EdsTemplate, operation_id="updateEdsTemplate")
async def update_template(id: TemplateId, body: EdsTemplateIn, authed: Editor) -> EdsTemplate:
    raw = await _proxy(authed).request("PUT", f"{API}/templates/{id}", json=_in(body))
    return EdsTemplate.model_validate(raw)


@router.post(
    "/eds/templates/{id}/reset", response_model=EdsTemplate, operation_id="resetEdsTemplate"
)
async def reset_template(id: TemplateId, authed: Editor) -> EdsTemplate:
    raw = await _proxy(authed).request("POST", f"{API}/templates/{id}/reset")
    return EdsTemplate.model_validate(raw)


@router.delete(
    "/eds/templates/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="deleteEdsTemplate",
)
async def delete_template(id: TemplateId, authed: Editor) -> Response:
    await _proxy(authed).request("DELETE", f"{API}/templates/{id}", expected=204)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/eds/template-previews",
    response_model=EdsTemplatePreview,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="previewEdsTemplate",
)
async def preview_template(body: EdsTemplatePreviewIn, authed: Reader) -> EdsTemplatePreview:
    raw = await _proxy(authed).request(
        "POST", f"{API}/template-previews", json=_in(body), expected=202
    )
    return EdsTemplatePreview.model_validate(raw)


@router.get(
    "/eds/template-previews/{id}",
    response_model=EdsTemplatePreview,
    operation_id="getEdsTemplatePreview",
)
async def get_preview(id: PreviewId, authed: Reader) -> EdsTemplatePreview:
    return EdsTemplatePreview.model_validate(
        await _proxy(authed).request("GET", f"{API}/template-previews/{id}")
    )


@router.get(
    "/eds/template-previews/{id}/file",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/pdf": {}}}},
    operation_id="downloadEdsTemplatePreview",
)
async def download_preview(id: PreviewId, authed: Reader) -> Response:
    response = await _proxy(authed).raw("GET", f"{API}/template-previews/{id}/file", stream=True)
    if response.status_code != 200:
        try:
            await response.aread()
            raise eds_error(response)
        finally:
            await response.aclose()
    headers = {
        "Content-Disposition": "inline",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    return FileStream(response, headers, "application/pdf")
