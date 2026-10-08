"""REST по лидам (SPEC §10.1): список, карточка, переписка, входящие, действия, решения."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import ContainerDep, require
from app.models.leads import Lead, Message
from app.models.qualification import Escalation
from app.repositories import crm
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
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1", tags=["leads"])

Reader = Annotated[Principal, Depends(require("leads", "read"))]
Taker = Annotated[Principal, Depends(require("leads", "take"))]
Worker = Annotated[Principal, Depends(require("leads", "work"))]
Replier = Annotated[Principal, Depends(require("leads", "reply"))]
Noter = Annotated[Principal, Depends(require("leads", "note"))]


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


def lead_out(lead: Lead, escalation: Escalation | None) -> LeadOut:
    return LeadOut(
        id=lead.id,
        display_name=lead.display_name,
        language=lead.language,
        stage=lead.stage,
        score=lead.score,
        owner_mode=lead.owner_mode,
        assigned_user_id=lead.assigned_user_id,
        need_summary=lead.need_summary,
        product_interest=list(lead.product_interest or []),
        last_lead_msg_at=lead.last_lead_msg_at,
        created_at=lead.created_at,
        escalation=escalation_out(escalation),
    )


def message_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        role=m.role,
        text=m.text,
        attachments=list(m.attachments or []),
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
) -> LeadPage:
    flt = crm.LeadFilter(stage, owner, min_score, language, q, created_from, created_to)
    async with container.session_factory() as session:
        rows, total = await crm.list_leads(session, flt, who.user_id, limit, offset, sort)
        escalations = await crm.active_escalations(session, [r.id for r in rows])
    return LeadPage(items=[lead_out(r, escalations.get(r.id)) for r in rows], total=total)


@router.get("/inbox", response_model=InboxResponse)
async def inbox(who: Reader, container: ContainerDep) -> InboxResponse:
    async with container.session_factory() as session:
        escalated, mine, unassigned = await crm.inbox(session, who.user_id)
        ids = [lead.id for lead in (*escalated, *mine, *unassigned)]
        escalations = await crm.active_escalations(session, ids)

    def out(rows: list[Lead]) -> list[LeadOut]:
        return [lead_out(r, escalations.get(r.id)) for r in rows]

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
            raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found")
        escalation = (await crm.active_escalations(session, [lead_id])).get(lead_id)
        username = await crm.tg_username(session, lead_id)
    base = lead_out(lead, escalation)
    return LeadDetail(
        **base.model_dump(),
        qualification=dict(lead.qualification or {}),
        consent_given_at=lead.consent_given_at,
        tg_username=username,
        notes_count=lead.notes_count,
        snoozed_until=lead.snoozed_until,
    )


@router.get("/leads/{lead_id}/messages", response_model=list[MessageOut])
async def lead_messages(
    lead_id: int,
    _: Reader,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    before_id: int | None = None,
) -> list[MessageOut]:
    async with container.session_factory() as session:
        rows = await crm.messages(session, lead_id, limit, before_id)
    return [message_out(m) for m in rows]


@router.post("/leads/{lead_id}/messages", response_model=ActionResult)
async def reply(lead_id: int, body: Reply, who: Replier, container: ContainerDep) -> ActionResult:
    return ActionResult(id=await container.lead_service.reply(who, lead_id, body.text))


@router.get("/leads/{lead_id}/notes", response_model=list[NoteOut])
async def lead_notes(lead_id: int, _: Reader, container: ContainerDep) -> list[NoteOut]:
    async with container.session_factory() as session:
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


@router.post("/leads/{lead_id}/actions/close_won", response_model=ActionResult)
async def close_won(
    lead_id: int, body: Close, who: Worker, container: ContainerDep
) -> ActionResult:
    await container.lead_service.close(who, lead_id, "won", body.reason)
    return ActionResult()


@router.post("/leads/{lead_id}/actions/close_lost", response_model=ActionResult)
async def close_lost(
    lead_id: int, body: Close, who: Worker, container: ContainerDep
) -> ActionResult:
    await container.lead_service.close(who, lead_id, "lost", body.reason)
    return ActionResult()


@router.post("/leads/{lead_id}/actions/note", response_model=ActionResult)
async def note(lead_id: int, body: NoteCreate, who: Noter, container: ContainerDep) -> ActionResult:
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
        lead = await leads_repo.get_lead(session, lead_id)
        if lead is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found")
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
