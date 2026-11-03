"""EDS · Шаблоны резолюций (контракт BFF: `/eds/resolution-templates`, EDS-REG, R2).

Эталоны — Directum RX, 1С:Документооборот 3.0. BFF не решает: кто видит и меняет шаблон, правила
«Для сведения» и активность сотрудников — EDS. Здесь — разделы каталога, ids сотрудников строками и
перевод ошибок EDS.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response
from pydantic import ValidationError

from app.clients.eds import eds_error
from app.deps import Authed, require_any
from app.errors import backend_unavailable
from app.schemas_eds_templates import (
    ResolutionTemplate,
    ResolutionTemplateIn,
    ResolutionTemplateList,
    to_template,
)

router = APIRouter(prefix="/eds/resolution-templates", tags=["letters"])

# Директор и делопроизводитель — свои и общие шаблоны; администратор — общие
# (читать — и директору с `admin: read`).
Reader = Annotated[
    Authed,
    Depends(require_any(("eds.inbox", "full"), ("eds.inbox.register", "full"), ("admin", "read"))),
]
Author = Annotated[
    Authed,
    Depends(require_any(("eds.inbox", "full"), ("eds.inbox.register", "full"), ("admin", "full"))),
]
TemplateId = Annotated[uuid.UUID, Path(alias="id")]
BASE = "/api/v1/resolution-templates"


async def _json(authed: Authed, method: str, path: str, ok: int, **kw: Any) -> Any:
    response = await authed.call("eds", method, path, **kw)
    if response.status_code != ok:
        raise eds_error(response)
    if ok == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise backend_unavailable("eds", "bad_response") from exc


def _one(raw: Any) -> ResolutionTemplate:
    try:
        return to_template(raw)
    except ValidationError as exc:
        raise backend_unavailable("eds", "bad_template") from exc


@router.get("", response_model=ResolutionTemplateList, operation_id="listResolutionTemplates")
async def list_resolution_templates(authed: Reader) -> ResolutionTemplateList:
    raw = await _json(authed, "GET", BASE, 200)
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise backend_unavailable("eds", "bad_template")
    return ResolutionTemplateList(items=[_one(item) for item in items])


@router.post(
    "", response_model=ResolutionTemplate, status_code=201, operation_id="createResolutionTemplate"
)
async def create_resolution_template(
    authed: Author, body: ResolutionTemplateIn
) -> ResolutionTemplate:
    return _one(await _json(authed, "POST", BASE, 201, json=body.for_eds()))


@router.put("/{id}", response_model=ResolutionTemplate, operation_id="updateResolutionTemplate")
async def update_resolution_template(
    authed: Author, template_id: TemplateId, body: ResolutionTemplateIn
) -> ResolutionTemplate:
    return _one(await _json(authed, "PUT", f"{BASE}/{template_id}", 200, json=body.for_eds()))


@router.delete(
    "/{id}", status_code=204, response_class=Response, operation_id="deleteResolutionTemplate"
)
async def delete_resolution_template(authed: Author, template_id: TemplateId) -> Response:
    await _json(authed, "DELETE", f"{BASE}/{template_id}", 204)
    return Response(status_code=204)
