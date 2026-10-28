"""Клиенты · Клиенты (W16-D1-2b, контракт: tag `clients`, 0.27.0): список, карточка 360°,
приглашение в кабинет.

BFF проксирует к CRM с токеном сотрудника; раздел каталога — `crm.clients`: список и карточка — от
чтения, «Отправить приглашение повторно» — полный; 403 — до CRM. Карточка собирается из четырёх
ответов CRM: клиент обязателен (нет — 404), контакты, заявки и документы — нет, раздел пустой и
помечен в `sources` как `unavailable`.
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from pydantic import TypeAdapter, ValidationError

from app.clients import crm_models as crm
from app.clients.crm_proxy import CrmProxy
from app.crm_clients_view import (
    CrmClientDetail,
    CrmClientItem,
    CrmContacts,
    CrmDeal,
    CrmDocument,
    client_card,
    client_row,
    recent_first,
)
from app.crm_leads_view import invitation_of
from app.deps import Authed, require
from app.errors import PlatformError
from app.schemas_crm_leads import ClientCard, ClientInvitation, ClientList, InvitationResendIn

router = APIRouter(tags=["clients"])

API = "/api/v1"
Reader = Annotated[Authed, Depends(require("crm.clients", "read"))]
Writer = Annotated[Authed, Depends(require("crm.clients", "full"))]
ClientId = Annotated[int, Path(ge=1)]


@router.get("/crm/clients", response_model=ClientList, operation_id="listCrmClients")
async def list_clients(
    authed: Reader, q: Annotated[str | None, Query(max_length=100)] = None
) -> ClientList:
    params = {"q": q.strip()} if q and q.strip() else None
    rows = await CrmProxy(authed.call).get_list(CrmClientItem, f"{API}/clients", params=params)
    return ClientList(items=recent_first([client_row(r) for r in rows]))


async def _part[T](proxy: CrmProxy, adapter: TypeAdapter[T], path: str, **params: Any) -> T | None:
    """Часть карточки: CRM не ответила или ответила не той формой — `None` (раздел без данных)."""
    try:
        body = await proxy.request("GET", path, params=params or None)
        return adapter.validate_python(body)
    except (PlatformError, ValidationError):
        return None


@router.get("/crm/clients/{id}", response_model=ClientCard, operation_id="getCrmClient")
async def get_client(id: ClientId, authed: Reader) -> ClientCard:
    proxy = CrmProxy(authed.call)
    detail, contacts, deals, documents = await asyncio.gather(
        proxy.get_model(CrmClientDetail, "GET", f"{API}/clients/{id}"),
        _part(proxy, TypeAdapter(CrmContacts), f"{API}/clients/{id}/contacts"),
        _part(proxy, TypeAdapter(list[CrmDeal]), f"{API}/deals", client_id=id),
        _part(proxy, TypeAdapter(list[CrmDocument]), f"{API}/documents", client_id=id),
    )
    return client_card(detail, contacts, deals, documents)


@router.post(
    "/crm/clients/{id}/invitation",
    response_model=ClientInvitation,
    operation_id="resendCrmClientInvitation",
)
async def resend_invitation(
    id: ClientId,
    body: InvitationResendIn,
    authed: Writer,
) -> ClientInvitation:
    out = await CrmProxy(authed.call).get_model(
        crm.InvitationOut, "POST", f"{API}/clients/{id}/invitation", json=body.model_dump()
    )
    return invitation_of(out)
