"""REST по лидам (SPEC §10.1): список, карточка, переписка, входящие, действия, решения.

Реестр (список, очередь, карточка, решения, действия над лидом) — только `leads:*` (раздел
`crm.leads`). Переписка (сообщения, заметки, ответ, подсказка, заметка) — `leads:*` или `chats:*`
с объектной проверкой диалога (B-D18-1, `app/api/dialog_access.py`).
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContainerDep, require
from app.api.dialog_access import dialog
from app.domain.client_requests import platform_status
from app.domain.errors import NotFoundError
from app.models.clients import Client
from app.models.leads import Lead, Message
from app.models.qualification import Escalation
from app.repositories import crm, lead_status, service_requests
from app.repositories import decisions as repo
from app.repositories import leads as leads_repo
from app.schemas.decisions import (
    DecisionsResponse,
    QualifierRunItem,
    TransitionItem,
    qualifier_summary,
)
from app.schemas.leads import (
    ActionResult,
    Assign,
    AssistOut,
    AssistRequest,
    Close,
    EscalationOut,
    InboxResponse,
    LeadDetail,
    LeadOut,
    LeadPage,
    MessageOut,
    NoteCreate,
    NoteOut,
    Reply,
    ReturnToBot,
    Snooze,
)
from app.schemas.notices import NoticeOut
from app.security.principal import Principal
from app.services import handoff_notes, web_lead_sla

router = APIRouter(prefix="/api/v1", tags=["leads"])

Reader = Annotated[Principal, Depends(require("leads", "read"))]
Taker = Annotated[Principal, Depends(require("leads", "take"))]
Worker = Annotated[Principal, Depends(require("leads", "work"))]
# Переписка диалога: реестр или участник/зона (B-D18-1).
DialogReader = Annotated[Principal, Depends(dialog("read"))]
DialogReplier = Annotated[Principal, Depends(dialog("reply"))]
DialogAssister = Annotated[Principal, Depends(dialog("assist"))]
DialogNoter = Annotated[Principal, Depends(dialog("note"))]


def escalation_out(e: Escalation | None) -> EscalationOut | None:
    if e is None:
        return None
    return EscalationOut(
        id=e.id,
        priority=e.priority,
        status=e.status,
        reason_codes=list(e.reason_codes or []),
        reason_text=e.reason_text,
        recommendation=e.recommendation,
        taken_by_user_id=e.taken_by_user_id,
        taken_at=e.taken_at,
        sla_due_at=e.sla_due_at,
        snoozed_until=e.snoozed_until,
        created_at=e.created_at,
    )


def _platform_status(lead: Lead, escalation: Escalation | None) -> str:
    asks_price, sla_overdue = lead_status.escalation_flags(escalation)
    return platform_status(lead.stage, asks_price=asks_price, sla_overdue=sla_overdue).value


def lead_out(
    lead: Lead, escalation: Escalation | None, names: dict[int, str] | None = None
) -> LeadOut:
    owner = lead.assigned_user_id
    return LeadOut(
        id=lead.id,
        display_name=lead.display_name,
        language=lead.language,
        stage=lead.stage,
        score=lead.score,
        owner_mode=lead.owner_mode,
        assigned_user_id=owner,
        assigned_user_name=(names or {}).get(owner) if owner is not None else None,
        client_id=lead.client_id,
        unread=_unread(lead),
        need_summary=lead.need_summary,
        product_interest=list(lead.product_interest or []),
        last_lead_msg_at=lead.last_lead_msg_at,
        created_at=lead.created_at,
        escalation=escalation_out(escalation),
        source=lead.source,
        platform_status=_platform_status(lead, escalation),
    )


async def _existing_lead(session: AsyncSession, lead_id: int) -> Lead:
    """404 для несуществующего или обезличенного лида, а не пустой список."""
    lead = await leads_repo.get_lead(session, lead_id)
    if lead is None or lead.erased_at is not None:
        raise NotFoundError("lead not found")
    return lead


def _unread(lead: Lead) -> bool:
    if lead.owner_mode != "human" or lead.last_lead_msg_at is None:
        return False
    return lead.last_human_msg_at is None or lead.last_lead_msg_at > lead.last_human_msg_at


# Ключи вложения, которые уходят клиентам API (D1-8, B-014): ключ хранилища (`storage_key`) не
# входит — файл отдаёт только маршрут вложения с проверкой доступа к лиду.
_ATTACHMENT_FIELDS = ("kind", "name", "mime", "size", "stored", "too_large", "note")


def attachment_out(item: object) -> dict[str, object]:
    """Вложение без адреса в хранилище: имя, тип, размер и признак «файл сохранён»."""
    if not isinstance(item, dict):
        return {}
    return {key: item[key] for key in _ATTACHMENT_FIELDS if key in item}


def message_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        role=m.role,
        text=m.text,
        attachments=[attachment_out(a) for a in m.attachments or []],
        sent_by_user_id=m.sent_by_user_id,
        created_at=m.created_at,
        meta=dict(m.meta or {}),
    )


@router.get("/leads", response_model=LeadPage)
async def list_leads(
    who: Reader,
    container: ContainerDep,
    stage: str | None = None,
    owner: str | None = Query(default=None, pattern=r"^(me|none|\d+)$"),
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    language: str | None = Query(default=None, pattern="^(ru|uz|en)$"),
    q: Annotated[str | None, Query(max_length=100)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: str = Query(default="last_message", pattern="^(last_message|score|created)$"),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    platform_status: Annotated[
        str | None,
        Query(
            pattern=r"^(new|dialog|wants_quote|no_answer|client|lost)(,(new|dialog|wants_quote|no_answer|client|lost))*$",
            description="Статус лида для Платформы (CRM-02), через запятую",
        ),
    ] = None,
    overdue: Annotated[
        bool | None, Query(description="Просроченные: открытая передача с истёкшим SLA ответа")
    ] = None,
) -> LeadPage:
    flt = crm.LeadFilter(
        stage, owner, min_score, language, q, created_from, created_to, platform_status, overdue
    )
    async with container.session_factory() as session:
        rows, total = await crm.list_leads(session, flt, who.user_id, limit, offset, sort)
        escalations = await crm.active_escalations(session, [r.id for r in rows])
        names = await crm.user_names(session, rows)
    return LeadPage(items=[lead_out(r, escalations.get(r.id), names) for r in rows], total=total)


@router.get("/inbox", response_model=InboxResponse)
async def inbox(
    who: Reader,
    container: ContainerDep,
    on_behalf_of: Annotated[int | None, Query(gt=0)] = None,
) -> InboxResponse:
    """Очередь работы с запиской передачи (CRM-06). Читает любой с `leads:read` (D1-1: директор
    видит «Ждут ответа» только для просмотра); забрать и ответить — права `leads:take`/`reply`.

    `on_behalf_of` — очередь замещаемого коллеги (W15-H6): только пока сегодня идёт период, где
    вызывающий назначен заместителем (иначе 403 `not_a_deputy`). Ответ — «мои» лиды замещаемого и
    общие эскалации; список «без ответственного» пуст: его заместитель и так видит в своей очереди.
    Права на сами объекты — свои, расширения нет."""
    if on_behalf_of is not None:
        await container.staff_deputy.require_covering(who.user_id, on_behalf_of)
    async with container.session_factory() as session:
        escalated, mine, unassigned = await crm.inbox(session, on_behalf_of or who.user_id)
        if on_behalf_of is not None:
            unassigned = []
        ids = [lead.id for lead in (*escalated, *mine, *unassigned)]
        escalations = await crm.active_escalations(session, ids)
        names = await crm.user_names(session, [*escalated, *mine, *unassigned])
        notes = await handoff_notes.notes(session, [*escalated, *mine, *unassigned], escalations)

    def out(rows: list[Lead]) -> list[LeadOut]:
        return [
            lead_out(r, escalations.get(r.id), names).model_copy(
                update={"handoff_note": notes.get(r.id)}
            )
            for r in rows
        ]

    ranked = sorted(
        escalated,
        key=lambda lead: crm.PRIORITY_RANK.get(
            escalations[lead.id].priority if lead.id in escalations else "info", 3
        ),
    )
    return InboxResponse(escalations=out(ranked), mine=out(mine), unassigned=out(unassigned))


@router.get("/leads/{lead_id}", response_model=LeadDetail)
async def get_lead(lead_id: int, _: Reader, container: ContainerDep) -> LeadDetail:
    async with container.session_factory() as session:
        lead = await leads_repo.get_lead(session, lead_id)
        if lead is None or lead.erased_at is not None:
            raise NotFoundError("lead not found")
        escalation = (await crm.active_escalations(session, [lead_id])).get(lead_id)
        username = await crm.tg_username(session, lead_id)
        phone = await crm.tg_phone(session, lead_id)
        client_phone = await crm.client_primary_phone(session, lead.client_id)
        names = await crm.user_names(session, [lead])
        request_id = await service_requests.open_request_id(session, lead)
        client = await session.get(Client, lead.client_id) if lead.client_id is not None else None
        erp_company_id = client.erp_company_id if client is not None else None
        confirmation = await container.client_notice_service.latest(
            session, lead_id, "web_confirmation"
        )
        invitation = (
            await container.portal_invites.current(session, client.id)
            if client is not None
            else None
        )
    base = lead_out(lead, escalation, names)
    mode = await container.backoffice_mode()
    now = datetime.now(UTC)
    waiting = web_lead_sla.awaiting(lead.first_response_due_at, lead.assigned_user_id)
    return LeadDetail(
        **base.model_dump(),
        qualification=dict(lead.qualification or {}),
        consent_given_at=lead.consent_given_at,
        consent_method=lead.consent_method,
        tg_username=username,
        phone_e164=lead.phone_e164 or phone,
        email=lead.email,
        company_name=lead.company_name,
        client_phone_e164=client_phone,
        notes_count=lead.notes_count,
        snoozed_until=lead.snoozed_until,
        open_service_request_id=request_id,
        backoffice_mode=mode.value,
        erp_company_id=erp_company_id,
        # Заявка, созданная передачей этого лида, а не последняя сделка лида (D-10).
        erp_deal_id=lead.erp_request_id,
        client_in_erp=erp_company_id is not None,
        client_handoff_status=client.erp_handoff_status if client is not None else None,
        client_handoff_error=client.erp_handoff_error if client is not None else None,
        first_response_due_at=lead.first_response_due_at if waiting else None,
        first_response_overdue=web_lead_sla.overdue(
            lead.first_response_due_at, lead.assigned_user_id, now
        ),
        confirmation=NoticeOut.model_validate(confirmation, from_attributes=True)
        if confirmation is not None
        else None,
        invitation=invitation,
    )


@router.get("/leads/{lead_id}/messages", response_model=list[MessageOut])
async def lead_messages(
    lead_id: int,
    _: DialogReader,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    before_id: int | None = None,
) -> list[MessageOut]:
    async with container.session_factory() as session:
        await _existing_lead(session, lead_id)
        rows = await crm.messages(session, lead_id, limit, before_id)
    return [message_out(m) for m in rows]


@router.post("/leads/{lead_id}/messages", response_model=ActionResult)
async def reply(
    lead_id: int, body: Reply, who: DialogReplier, container: ContainerDep
) -> ActionResult:
    message_id = await container.lead_service.reply(
        who, lead_id, body.text, client_message_id=body.client_message_id
    )
    return ActionResult(id=message_id)


@router.post("/leads/{lead_id}/assist", response_model=AssistOut)
async def assist(
    lead_id: int, body: AssistRequest, who: DialogAssister, container: ContainerDep
) -> AssistOut:
    """ИИ-помощь менеджеру (Q-019): текст для поля ответа; клиенту ничего не отправляется."""
    result = await container.assist_service.assist(who, lead_id, body.mode, body.text)
    return AssistOut(text=result.text, cost_usd=result.cost_usd, notice=result.notice)


@router.get("/leads/{lead_id}/notes", response_model=list[NoteOut])
async def lead_notes(lead_id: int, _: DialogReader, container: ContainerDep) -> list[NoteOut]:
    async with container.session_factory() as session:
        await _existing_lead(session, lead_id)
        rows = await crm.notes(session, lead_id)
    return [
        NoteOut(
            id=n.id,
            user_id=n.user_id,
            text=n.text,
            visible_to_bot=n.visible_to_bot,
            created_at=n.created_at,
        )
        for n in rows
    ]


@router.post("/leads/{lead_id}/actions/take", response_model=ActionResult)
async def take(lead_id: int, who: Taker, container: ContainerDep) -> ActionResult:
    await container.lead_service.take(who, lead_id)
    return ActionResult()


@router.post("/leads/{lead_id}/actions/acknowledge", response_model=ActionResult)
async def acknowledge(lead_id: int, who: Taker, container: ContainerDep) -> ActionResult:
    """«Принято к сведению»: закрыть информационную передачу, лид остаётся у бота."""
    await container.lead_service.acknowledge(who, lead_id)
    return ActionResult()


@router.post("/leads/{lead_id}/actions/return_to_bot", response_model=ActionResult)
async def return_to_bot(
    lead_id: int, body: ReturnToBot, who: Worker, container: ContainerDep
) -> ActionResult:
    await container.lead_service.return_to_bot(who, lead_id, body.note)
    return ActionResult()


@router.post("/leads/{lead_id}/actions/snooze", response_model=ActionResult)
async def snooze(lead_id: int, body: Snooze, who: Worker, container: ContainerDep) -> ActionResult:
    await container.lead_service.snooze(who, lead_id, body.until)
    return ActionResult()


@router.post("/leads/{lead_id}/actions/unsnooze", response_model=ActionResult)
async def unsnooze(lead_id: int, who: Worker, container: ContainerDep) -> ActionResult:
    """«Вернуть из отложенных»: передача снова открыта, срок реакции — заново."""
    await container.lead_service.unsnooze(who, lead_id)
    return ActionResult()


@router.post("/leads/{lead_id}/actions/close_won", response_model=ActionResult)
async def close_won(
    lead_id: int, body: Close, who: Worker, container: ContainerDep
) -> ActionResult:
    """«Сделка заключена». С коннектором ERP — 409 `won_decided_by_erp` (ADR-0022): итог придёт
    событием `deal.won`, закрыть лид можно только отказом."""
    await container.lead_service.close(
        who, lead_id, "won", body.reason, amount=body.amount, lost_reason=body.lost_reason
    )
    return ActionResult()


@router.post("/leads/{lead_id}/actions/close_lost", response_model=ActionResult)
async def close_lost(
    lead_id: int, body: Close, who: Worker, container: ContainerDep
) -> ActionResult:
    await container.lead_service.close(
        who, lead_id, "lost", body.reason, amount=body.amount, lost_reason=body.lost_reason
    )
    return ActionResult()


@router.post("/leads/{lead_id}/actions/new_deal", response_model=ActionResult)
async def new_deal(lead_id: int, who: Worker, container: ContainerDep) -> ActionResult:
    await container.lead_service.new_deal(who, lead_id)
    return ActionResult()


@router.post("/leads/{lead_id}/actions/assign", response_model=ActionResult)
async def assign(lead_id: int, body: Assign, who: Worker, container: ContainerDep) -> ActionResult:
    await container.lead_service.assign(who, lead_id, body.user_id)
    return ActionResult()


@router.post("/leads/{lead_id}/actions/note", response_model=ActionResult)
async def note(
    lead_id: int, body: NoteCreate, who: DialogNoter, container: ContainerDep
) -> ActionResult:
    note_id = await container.lead_service.add_note(who, lead_id, body.text, body.visible_to_bot)
    return ActionResult(id=note_id)


@router.get("/leads/{lead_id}/decisions", response_model=DecisionsResponse)
async def lead_decisions(
    lead_id: int,
    _: Reader,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DecisionsResponse:
    async with container.session_factory() as session:
        lead = await _existing_lead(session, lead_id)
        runs = await repo.qualifier_runs(session, lead_id, limit)
        moves = await repo.transitions(session, lead_id, limit)
    items: list[QualifierRunItem | TransitionItem] = [
        QualifierRunItem(
            kind="qualifier",
            id=r.id,
            at=r.created_at,
            proposed_stage=r.proposed_stage,
            applied_stage=r.applied_stage,
            rejected_reason=r.rejected_reason,
            score_before=r.score_before,
            score_after=r.score_after,
            triggers_fired=list(r.triggers_fired or []),
            escalated=r.escalated,
            error=r.error,
            model=r.model,
            cost_usd=r.cost_usd,
            trace_id=r.trace_id,
            **qualifier_summary(r.output),
        )
        for r in runs
    ]
    items += [
        TransitionItem(
            kind="transition",
            id=t.id,
            at=t.created_at,
            from_stage=t.from_stage,
            to_stage=t.to_stage,
            source=t.source,
            actor_user_id=t.actor_user_id,
            reason=t.reason,
        )
        for t in moves
    ]
    items.sort(key=lambda i: i.at, reverse=True)
    return DecisionsResponse(
        lead_id=lead.id,
        stage=lead.stage,
        score=lead.score,
        owner_mode=lead.owner_mode,
        items=items[:limit],
    )
