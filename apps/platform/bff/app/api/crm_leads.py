"""Клиенты · Лиды (W16-D1-2b, контракт: tag `leads`): список и карточка лида.

BFF проксирует к CRM с токеном сотрудника; раздел каталога — `crm.leads` от чтения, 403 — до CRM.
Вкладка — статус Платформы CRM `platform_status` (CRM-02), «мои» — `owner=me`, «просроченные» —
`overdue=true`, канал — `source`; страница и итог — у CRM. Карточка — `GET /leads/{id}`, последние
сообщения, клиент лида; без сообщений или клиента карточка всё равно открывается.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Path, Query, status

from app.api.crm_messages import _Crm, _lead_id
from app.clients import crm_models as crm
from app.clients.crm_proxy import CrmProxy, crm_error
from app.crm_leads_view import client_short, lead_card, lead_row, list_params
from app.deps import Authed, require, require_any
from app.errors import PlatformError, backend_unavailable
from app.feeds.numbers import lead_number
from app.schemas_crm_leads import LeadCard, LeadCreated, LeadIn, LeadPage, LeadScope, LeadTab

router = APIRouter(tags=["leads"])

API = "/api/v1"
# Реестр лидов или первая линия (`crm.leads.triage`, D17G-1).
Reader = Annotated[
    Authed, Depends(require_any(("crm.leads", "read"), ("crm.leads.triage", "full")))
]
LeadParam = Annotated[str, Path(pattern=r"^[Ll]-?\d{1,9}$")]
Creator = Annotated[Authed, Depends(require("crm.leads", "full"))]


@router.get("/crm/leads", response_model=LeadPage, operation_id="listCrmLeads")
async def list_leads(
    authed: Reader,
    tab: LeadTab = "all",
    scope: LeadScope = "all",
    q: Annotated[str | None, Query(max_length=100)] = None,
    channel: Annotated[str | None, Query(pattern=r"^[a-z][a-z_]{0,15}$")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> LeadPage:
    api = _Crm(authed)
    params = list_params(tab, scope, q, channel, offset, limit)
    raw = await api.json("GET", f"{API}/leads", params=params)
    body = raw if isinstance(raw, dict) else {}
    leads = [crm.LeadOut.model_validate(item) for item in body.get("items") or []]
    total = body.get("total")
    now = datetime.now(UTC)
    return LeadPage(
        items=[lead_row(lead, {}, now) for lead in leads],
        total=total if isinstance(total, int) and total >= 0 else len(leads),
    )


async def _soft(api: _Crm, path: str, params: dict[str, Any] | None = None) -> Any:
    """Дополнение карточки: сбой CRM — без него, карточка открывается."""
    try:
        return await api.json("GET", path, params=params)
    except PlatformError:
        return None


@router.get("/crm/leads/{lead}", response_model=LeadCard, operation_id="getCrmLead")
async def get_lead(lead: LeadParam, authed: Reader) -> LeadCard:
    lead_id = _lead_id(lead)
    api = _Crm(authed)
    raw, names, messages_raw = await asyncio.gather(
        api.json("GET", f"{API}/leads/{lead_id}"),
        api.names(),
        _soft(api, f"{API}/leads/{lead_id}/messages", {"limit": 5}),
    )
    detail = crm.LeadDetail.model_validate(raw)
    client_raw, products = await asyncio.gather(
        _soft(api, f"{API}/clients/{detail.client_id}") if detail.client_id else _none(),
        api.products(list(detail.product_interest)),
    )
    messages = [crm.MessageOut.model_validate(m) for m in messages_raw or []]
    return lead_card(detail, names, products, messages, client_short(client_raw, detail))


async def _none() -> None:
    return None


def _create_error(response: httpx.Response) -> PlatformError:
    """Отказ CRM на «новый лид»: поле — в `fields`, дубль — номер лида или id клиента."""
    error = crm_error(response)
    try:
        raw = response.json()["details"]
    except (ValueError, KeyError, TypeError):
        raw = None
    details = raw if isinstance(raw, dict) else {}
    extra: dict[str, Any] = {}
    field = details.get("field")
    if isinstance(field, str) and field in ("phone", "email", "name", "company", "need"):
        extra["fields"] = [field]
    lead_id = details.get("lead_id")
    if isinstance(lead_id, int) and not isinstance(lead_id, bool):
        extra["lead"] = lead_number(lead_id)
    client_id = details.get("client_id")
    if isinstance(client_id, int) and not isinstance(client_id, bool):
        extra["client_id"] = client_id
    if extra:
        error.body.details = {**(error.body.details or {}), **extra}
    return error


@router.post(
    "/crm/leads",
    response_model=LeadCreated,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCrmLead",
)
async def create_lead(body: LeadIn, authed: Creator) -> LeadCreated:
    """«Создать · Лид» (план 2026-11-12 п. 0.1): CRM `POST /leads`, создавший — ответственный."""
    response = await CrmProxy(authed.call).raw(
        "POST", f"{API}/leads", json=body.model_dump(exclude_none=True)
    )
    if response.status_code not in (200, 201):
        raise _create_error(response)
    try:
        created = response.json()["id"]
    except (ValueError, KeyError, TypeError) as exc:
        raise backend_unavailable("crm", "bad_response") from exc
    if not isinstance(created, int) or isinstance(created, bool):
        raise backend_unavailable("crm", "bad_response")
    return LeadCreated(lead=lead_number(created))
