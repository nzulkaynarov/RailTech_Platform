"""Документы · Шаблоны · Договоры (ДОК-10): список, новая редакция, «На утверждение», «Утвердить».

BFF не решает: статус, редакция, право утверждать (`contract.approve_template`, держатель зоны
«Право») и закреплённый текст — в ERP (`crm/document-templates`). Здесь — разделы каталога и
перевод ответа ERP в контракт.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.admin_company import _erp
from app.deps import Authed, require_any
from app.schemas_contract_templates import (
    ContractTemplate,
    ContractTemplateIn,
    ContractTemplateList,
    ContractTemplateRoleIn,
    OfferedContractTemplates,
    to_contract_template,
    to_offered,
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
