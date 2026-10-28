"""Чаты · С клиентами (B-D18-1, W18A-P3): диалоги с клиентами, открытые сотруднику.

`GET /chats/external` → CRM `GET /chats` с токеном сотрудника. Раздел `chats.external` или
`crm.leads` от чтения — BFF отсекает заведомо лишних (403 до CRM), а какие диалоги открыты, решает
CRM: держателю `crm.leads` — все (`access = registry`), держателю только `chats.external` — где он
участвует (`participant`) и сделки клиента со счётом в зоне «Счета и оплаты» (`invoiced`). Переписка
диалога — `GET /crm/messages/{lead}/thread` и вложения с той же проверкой в CRM; карточка лида
(`GET /crm/messages/{lead}`) — только `crm.leads`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.clients import crm_models as crm
from app.clients.crm_proxy import CrmProxy
from app.crm_messages_view import channel, language, person
from app.deps import Authed, require_any
from app.errors import PlatformError
from app.feeds.numbers import lead_number
from app.schemas_chats import ExternalChat, ExternalChatList

router = APIRouter(tags=["chats"])

API = "/api/v1"
# Те же разделы, что у переписки диалога (`crm_messages.DialogReader`).
Reader = Annotated[Authed, Depends(require_any(("chats.external", "read"), ("crm.leads", "read")))]


async def _names(proxy: CrmProxy) -> dict[int, str]:
    """Имена ответственных (`GET /team`, `leads:read` или `chats:read`); сбой — «#id»."""
    try:
        rows = await proxy.get_list(crm.TeamMember, f"{API}/team")
    except PlatformError:
        return {}
    return {row.id: row.full_name for row in rows}


@router.get("/chats/external", response_model=ExternalChatList, operation_id="listExternalChats")
async def list_external_chats(
    authed: Reader,
    erp_deal_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExternalChatList:
    proxy = CrmProxy(authed.call)
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if erp_deal_id is not None:
        params["erp_deal_id"] = erp_deal_id
    page = await proxy.get_model(crm.DialogPage, "GET", f"{API}/chats", params=params)
    names = await _names(proxy) if any(d.assigned_user_id for d in page.items) else {}
    return ExternalChatList(
        items=[
            ExternalChat(
                lead=lead_number(d.lead_id),
                name=d.display_name or lead_number(d.lead_id),
                channel=channel(d.source),
                language=language(d.language),
                last_message_at=d.last_message_at,
                assigned=person(d.assigned_user_id, names),
                invoiced=d.invoiced,
                access=d.access.value,
            )
            for d in page.items
        ],
        total=page.total,
    )
