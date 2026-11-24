"""Группы Telegram с секретарём (ТГ-1б, ADR-0032, контракт: tag `telegram-groups`).

BFF проксирует `/api/v1/telegram-groups` CRM с токеном сотрудника. Права — раздел `crm.clients`
(в CRM — `clients:read` / `clients:write`): список и группа клиента для карточки — от чтения,
привязка и отключение — полный; 403 — до CRM, отказы CRM переводятся в `Error`. Состояние группы
(`waiting_code` … `removed`) считает BFF из ответа CRM. Переписка группы — обычная лента лида
`GET /crm/messages/{lead}/thread` по номеру якорного лида.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.clients import crm_models as crm
from app.clients.crm_proxy import CrmProxy
from app.deps import Authed, require
from app.feeds.numbers import lead_number
from app.schemas_crm_telegram_groups import (
    ClientTelegramGroup,
    GroupState,
    TelegramGroup,
    TelegramGroupBindIn,
    TelegramGroupList,
)
from app.schemas_integrations import ActionOk

router = APIRouter(tags=["telegram-groups"])

API = "/api/v1/telegram-groups"
PAGE = 200
Reader = Annotated[Authed, Depends(require("crm.clients", "read"))]
Writer = Annotated[Authed, Depends(require("crm.clients", "full"))]
ChatId = Annotated[int, Path()]


def _state(row: crm.TelegramGroupOut) -> GroupState:
    status = row.status.value
    if status == "bound":
        return "needs_admin" if row.access.value == "admin_required" else "connected"
    if status == "pending":
        return "waiting_code" if row.code_active else "code_expired"
    return "disconnected" if status == "unbound" else "removed"


def group_of(row: crm.TelegramGroupOut) -> TelegramGroup:
    return TelegramGroup(
        chat_id=row.chat_id,
        title=row.title,
        state=_state(row),
        client_id=row.client_id,
        client_name=row.client_name,
        lead=lead_number(row.lead_id) if row.lead_id is not None else None,
        bound_at=row.bound_at,
        detected_at=row.detected_at,
    )


async def _all(authed: Authed) -> list[crm.TelegramGroupOut]:
    return await CrmProxy(authed.call).get_list(
        crm.TelegramGroupOut, API, params={"limit": PAGE, "offset": 0}
    )


@router.get(
    "/crm/telegram-groups", response_model=TelegramGroupList, operation_id="listCrmTelegramGroups"
)
async def list_groups(authed: Reader) -> TelegramGroupList:
    return TelegramGroupList(items=[group_of(row) for row in await _all(authed)])


@router.post(
    "/crm/telegram-groups/bind", response_model=TelegramGroup, operation_id="bindCrmTelegramGroup"
)
async def bind_group(body: TelegramGroupBindIn, authed: Writer) -> TelegramGroup:
    """Привязать группу к клиенту по коду из группы; неверный или просроченный код — 404/409 CRM."""
    row = await CrmProxy(authed.call).get_model(
        crm.TelegramGroupOut,
        "POST",
        f"{API}/bind",
        json={"code": body.code.strip(), "client_id": body.client_id},
    )
    return group_of(row)


@router.post(
    "/crm/telegram-groups/{chat_id}/unbind",
    response_model=ActionOk,
    operation_id="unbindCrmTelegramGroup",
)
async def unbind_group(chat_id: ChatId, authed: Writer) -> ActionOk:
    """Отключить группу: запись прекращается, прежняя переписка остаётся у клиента."""
    await CrmProxy(authed.call).get_model(crm.ActionResult, "POST", f"{API}/{chat_id}/unbind")
    return ActionOk(id=None, ok=True)


@router.get(
    "/crm/clients/{id}/telegram-group",
    response_model=ClientTelegramGroup,
    operation_id="getCrmClientTelegramGroup",
)
async def client_group(id: Annotated[int, Path(ge=1)], authed: Reader) -> ClientTelegramGroup:
    """Привязанная группа клиента для его карточки; нет группы — `group: null`."""
    rows = await _all(authed)
    found = next((r for r in rows if r.client_id == id and r.status.value == "bound"), None)
    return ClientTelegramGroup(group=group_of(found) if found else None)
