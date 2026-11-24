"""Ручки лида (LH-1, контракт: теги `messages` и `leads`): закрыть, передать коллеге, отбросить как
спам, тест или дубль, открыть заново, «Принято к сведению», отложить, правка контактов.

BFF проксирует к CRM с токеном сотрудника и проверяет раздел `crm.leads: full`. Права действия
(владелец лида, стадия, открытая передача) решает CRM: её отказы переводятся в `Error` с кодом CRM
в `details.reason`, ошибка поля формы — в `details.fields`. «Открыть заново» выбирает действие CRM
по стадии лида: из «Отказа» — «Забрать» (возвращает и отброшенного), у клиента — «Новая сделка».
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.crm_messages import API, LeadParam, Worker, _Crm, _lead_id
from app.clients import crm_models as crm
from app.clients.crm_proxy import CrmProxy
from app.crm_messages_view import person
from app.deps import Authed, require
from app.errors import PlatformError
from app.feeds.numbers import lead_id_of, lead_number
from app.schemas_crm_lead_actions import (
    AssignLeadIn,
    CloseLeadIn,
    CloseOptions,
    DiscardLeadIn,
    LeadContactsIn,
    LeadContactsSaved,
    LeadDuplicate,
    SnoozeLeadIn,
    SnoozePeriod,
)
from app.schemas_crm_messages import LeadManagerList
from app.schemas_integrations import ActionOk

router = APIRouter(tags=["messages"])

Editor = Annotated[Authed, Depends(require("crm.leads", "full"))]
_SNOOZE: dict[SnoozePeriod, timedelta] = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "three_days": timedelta(days=3),
}
OK = ActionOk(id=None, ok=True)


@router.get(
    "/crm/lead-close-options", response_model=CloseOptions, operation_id="getCrmCloseOptions"
)
async def close_options(authed: Worker) -> CloseOptions:
    raw = await _Crm(authed).json("GET", f"{API}/leads/close_options")
    options = crm.CloseOptions.model_validate(raw)
    return CloseOptions(lost_reasons=options.lost_reasons, won_by_erp=options.won_by_erp)


@router.get(
    "/crm/lead-colleagues", response_model=LeadManagerList, operation_id="listCrmLeadColleagues"
)
async def lead_colleagues(authed: Worker) -> LeadManagerList:
    """Кому передать взятого лида: активные менеджеры, кроме самого сотрудника."""
    rows = await CrmProxy(authed.call).get_list(crm.TeamMember, f"{API}/team")
    items = [
        person(row.id, {row.id: row.full_name})
        for row in rows
        if row.id != int(authed.data.user_id)
    ]
    return LeadManagerList(items=[item for item in items if item is not None])


@router.post("/crm/messages/{lead}/close", response_model=ActionOk, operation_id="closeCrmLead")
async def close(lead: LeadParam, body: CloseLeadIn, authed: Editor) -> ActionOk:
    await _Crm(authed).json(
        "POST",
        f"{API}/leads/{_lead_id(lead)}/actions/close_{body.outcome}",
        body={"reason": body.reason, "lost_reason": body.lost_reason},
    )
    return OK


@router.post("/crm/messages/{lead}/assign", response_model=ActionOk, operation_id="assignCrmLead")
async def assign(lead: LeadParam, body: AssignLeadIn, authed: Editor) -> ActionOk:
    await _Crm(authed).json(
        "POST", f"{API}/leads/{_lead_id(lead)}/actions/assign", body={"user_id": int(body.user_id)}
    )
    return OK


@router.post("/crm/messages/{lead}/discard", response_model=ActionOk, operation_id="discardCrmLead")
async def discard(lead: LeadParam, body: DiscardLeadIn, authed: Editor) -> ActionOk:
    target = lead_id_of(body.duplicate_of) if body.duplicate_of else None
    await _Crm(authed).json(
        "POST",
        f"{API}/leads/{_lead_id(lead)}/actions/discard",
        body={"kind": body.kind, "duplicate_of": target},
    )
    return OK


@router.post("/crm/messages/{lead}/reopen", response_model=ActionOk, operation_id="reopenCrmLead")
async def reopen(lead: LeadParam, authed: Editor) -> ActionOk:
    api = _Crm(authed)
    lead_id = _lead_id(lead)
    raw = await api.json("GET", f"{API}/leads/{lead_id}")
    stage = raw.get("stage") if isinstance(raw, dict) else None
    action = {"lost": "take", "customer": "new_deal"}.get(str(stage))
    if action is None:
        raise PlatformError(
            "CONFLICT",
            "Лид не закрыт.",
            status_code=409,
            details={"reason": "not_closed"},
        )
    await api.json("POST", f"{API}/leads/{lead_id}/actions/{action}")
    return OK


@router.post(
    "/crm/messages/{lead}/acknowledge", response_model=ActionOk, operation_id="acknowledgeCrmLead"
)
async def acknowledge(lead: LeadParam, authed: Editor) -> ActionOk:
    await _Crm(authed).json("POST", f"{API}/leads/{_lead_id(lead)}/actions/acknowledge")
    return OK


@router.post("/crm/messages/{lead}/snooze", response_model=ActionOk, operation_id="snoozeCrmLead")
async def snooze(lead: LeadParam, body: SnoozeLeadIn, authed: Editor) -> ActionOk:
    until = datetime.now(UTC) + _SNOOZE[body.period]
    await _Crm(authed).json(
        "POST", f"{API}/leads/{_lead_id(lead)}/actions/snooze", body={"until": until.isoformat()}
    )
    return OK


@router.post(
    "/crm/messages/{lead}/unsnooze", response_model=ActionOk, operation_id="unsnoozeCrmLead"
)
async def unsnooze(lead: LeadParam, authed: Editor) -> ActionOk:
    await _Crm(authed).json("POST", f"{API}/leads/{_lead_id(lead)}/actions/unsnooze")
    return OK


@router.patch(
    "/crm/leads/{lead}",
    response_model=LeadContactsSaved,
    tags=["leads"],
    operation_id="updateCrmLead",
)
async def update_lead(lead: LeadParam, body: LeadContactsIn, authed: Editor) -> LeadContactsSaved:
    """Правка имени, телефона, почты и компании (CRM `PATCH /leads/{id}`); дубль — в ответе."""
    raw = await _Crm(authed).json(
        "PATCH", f"{API}/leads/{_lead_id(lead)}", body=body.model_dump(exclude_unset=True)
    )
    result = crm.ContactsResult.model_validate(raw)
    return LeadContactsSaved(
        duplicates=[
            LeadDuplicate(
                kind=d.kind.value,
                lead=lead_number(d.id) if d.kind.value == "lead" else None,
                client_id=d.id if d.kind.value == "client" else None,
                name=d.name,
                field=d.field.value,
            )
            for d in result.duplicates or []
        ]
    )
