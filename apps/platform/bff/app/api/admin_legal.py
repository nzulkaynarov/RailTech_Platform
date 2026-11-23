"""«Настройки · Оферта и политика» (ДВ-5, тег `legal-editions`): редакции и журнал акцептов.

BFF проксирует к ERP `settings/legal-editions/` и `settings/legal-acceptances/` с токеном
сотрудника и проверяет раздел каталога `company.settings` (чтение — `read`, изменения и
публикация — `full`: правило компании, его правят директор и администратор). Право на
изменения решает и ERP (`settings.edit`). Публикация и акцепты пишутся в журналы ERP.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.clients.erp_company import ErpCompany
from app.deps import Authed, require
from app.schemas_legal import (
    LegalAcceptancePage,
    LegalEditionCreate,
    LegalEditionDetail,
    LegalEditionList,
    LegalEditionUpdate,
    to_acceptance_page,
    to_edition,
    to_edition_list,
)

router = APIRouter(tags=["legal-editions", "admin"])

Reader = Annotated[Authed, Depends(require("company.settings", "read"))]
Writer = Annotated[Authed, Depends(require("company.settings", "full"))]
EditionId = Annotated[str, Path(pattern=r"^[0-9]+$")]

EDITIONS = "settings/legal-editions/"
ACCEPTANCES = "settings/legal-acceptances/"


def _erp(authed: Authed) -> ErpCompany:
    return ErpCompany(authed.call)


@router.get(
    "/admin/legal-editions",
    response_model=LegalEditionList,
    response_model_exclude_none=True,
    operation_id="listLegalEditions",
)
async def list_editions(authed: Reader) -> LegalEditionList:
    return to_edition_list(await _erp(authed).data("GET", EDITIONS))


@router.post(
    "/admin/legal-editions",
    response_model=LegalEditionDetail,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    operation_id="createLegalEdition",
)
async def create_edition(body: LegalEditionCreate, authed: Writer) -> LegalEditionDetail:
    return to_edition(await _erp(authed).data("POST", EDITIONS, json=body.sent()))


@router.get(
    "/admin/legal-editions/{id}",
    response_model=LegalEditionDetail,
    response_model_exclude_none=True,
    operation_id="getLegalEdition",
)
async def get_edition(id: EditionId, authed: Reader) -> LegalEditionDetail:
    return to_edition(await _erp(authed).data("GET", f"{EDITIONS}{id}/"))


@router.patch(
    "/admin/legal-editions/{id}",
    response_model=LegalEditionDetail,
    response_model_exclude_none=True,
    operation_id="updateLegalEdition",
)
async def update_edition(
    id: EditionId, body: LegalEditionUpdate, authed: Writer
) -> LegalEditionDetail:
    return to_edition(await _erp(authed).data("PATCH", f"{EDITIONS}{id}/", json=body.sent()))


@router.delete(
    "/admin/legal-editions/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="deleteLegalEdition",
)
async def delete_edition(id: EditionId, authed: Writer) -> Response:
    await _erp(authed).request("DELETE", f"{EDITIONS}{id}/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/admin/legal-editions/{id}/publish",
    response_model=LegalEditionDetail,
    response_model_exclude_none=True,
    operation_id="publishLegalEdition",
)
async def publish_edition(id: EditionId, authed: Writer) -> LegalEditionDetail:
    return to_edition(await _erp(authed).data("POST", f"{EDITIONS}{id}/publish/"))


@router.get(
    "/admin/legal-acceptances",
    response_model=LegalAcceptancePage,
    response_model_exclude_none=True,
    operation_id="listLegalAcceptances",
)
async def list_acceptances(
    authed: Reader,
    edition: Annotated[str, Query(pattern=r"^[0-9]*$")] = "",
    q: Annotated[str, Query(max_length=100)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> LegalAcceptancePage:
    params: dict[str, str | int] = {"page": page, "page_size": page_size}
    if edition:
        params["edition"] = edition
    if q.strip():
        params["q"] = q.strip()
    raw = await _erp(authed).data("GET", ACCEPTANCES, params=params)
    return to_acceptance_page(raw, page=page, page_size=page_size)
