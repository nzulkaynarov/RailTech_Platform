"""Чтение маршрутов: карточка (шаги, чек-лист и снимок КП, что можно решить) и очередь «ждёт меня»."""

import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import not_found
from app.models import ApprovalRoute, ApprovalStep, Document, Employee
from app.schemas.approvals import (
    Approval,
    ApprovalListItem,
    ApprovalObject,
    ApprovalPage,
    ApprovalTemplate,
    ChecklistItem,
    Decision,
    QuoteSnapshot,
    RouteStatus,
    StepAssignee,
)
from app.schemas.approvals import ApprovalStep as StepOut
from app.schemas.pagination import decode_cursor
from app.security.permissions import EdsPermission as P
from app.services import access, approvals, checklist, paging
from app.services.people import Directory, load_directory


def object_of(route: ApprovalRoute, document: Document | None) -> ApprovalObject:
    if route.template == ApprovalTemplate.QUOTE.value:
        return ApprovalObject(
            kind=ApprovalTemplate.QUOTE,
            erp_quote_id=route.erp_quote_id,
            quote_number=route.quote_number,
            quote_version=route.quote_version,
            erp_deal_id=route.erp_deal_id,
            deal_number=route.deal_number,
        )
    return ApprovalObject(
        kind=ApprovalTemplate(route.template),
        document_id=route.document_id,
        number=document.number if document else None,
        deal_number=document.deal_number if document else None,
    )


def step_of(step: ApprovalStep, directory: Directory) -> StepOut:
    return StepOut(
        index=step.index,
        label=step.label,
        assignee=StepAssignee(crm_user_id=step.assignee_crm_user_id, permission=step.assignee_permission),
        status=step.status,
        decided_by=directory.person_or_none(step.decided_by),
        decided_at=step.decided_at,
        comment=step.comment,
    )


async def get_visible(session: AsyncSession, employee: Employee, route_id: uuid.UUID) -> ApprovalRoute:
    """Маршрут, если сотрудник автор объекта, участник (в т. ч. держатель права шага) или у него `registry.read`."""
    stmt = select(ApprovalRoute).where(ApprovalRoute.id == route_id, access.route_visible(employee))
    route = (await session.execute(stmt)).scalar_one_or_none()
    if route is None:
        raise not_found("Маршрут не найден.")
    return route


def _hide_margin(items: list[ChecklistItem]) -> list[ChecklistItem]:
    """Тем, кто не решает КП, значение маржи (производное от себестоимости) не показывается."""
    return [item.model_copy(update={"value": None}) if item.code == "margin" else item for item in items]


async def present(session: AsyncSession, employee: Employee, route: ApprovalRoute) -> Approval:
    steps = await approvals.load_steps(session, route.id)
    directory = await load_directory(session, (s.decided_by for s in steps))
    document = await session.get(Document, route.document_id) if route.document_id else None
    is_quote = route.template == ApprovalTemplate.QUOTE.value
    decider = access.has(employee, P.APPROVALS_DECIDE)
    items: list[ChecklistItem] = []
    if is_quote:
        items = checklist.build(route.quote_snapshot or {}, await checklist.resolution_threshold(session, route))
    current = next((s for s in steps if s.index == route.current_step), None)
    can_decide = (
        route.status == RouteStatus.OPEN.value
        and current is not None
        and await approvals.may_decide(session, employee, route.id, current.index)
    )
    allowed: list[Decision] = []
    if can_decide:
        allowed = [Decision.RETURN, Decision.REJECT]
        if checklist.is_green(items):
            allowed.insert(0, Decision.APPROVE)
    return Approval(
        id=route.id,
        template=ApprovalTemplate(route.template),
        title=route.title,
        object=object_of(route, document),
        status=RouteStatus(route.status),
        round=route.round,
        steps=[step_of(s, directory) for s in steps],
        checklist=items if decider or not is_quote else _hide_margin(items),
        quote=QuoteSnapshot.model_validate(route.quote_snapshot)
        if is_quote and decider and route.quote_snapshot
        else None,
        can_decide=can_decide,
        allowed_decisions=allowed,
        outgoing_number=route.outgoing_number,
        created_at=route.created_at,
        closed_at=route.closed_at,
    )


async def list_page(
    session: AsyncSession,
    employee: Employee,
    *,
    mine: bool,
    statuses: list[RouteStatus] | None,
    templates: list[ApprovalTemplate] | None,
    cursor: str | None,
    limit: int,
) -> ApprovalPage:
    stmt = select(ApprovalRoute)
    if mine:
        waiting = exists(
            select(1).where(
                ApprovalStep.approval_id == ApprovalRoute.id,
                ApprovalStep.index == ApprovalRoute.current_step,
                access.step_open_to(employee),
            )
        )
        stmt = stmt.where(ApprovalRoute.status == RouteStatus.OPEN.value, waiting)
    else:
        stmt = stmt.where(access.route_visible(employee))
    if statuses:
        stmt = stmt.where(ApprovalRoute.status.in_([s.value for s in statuses]))
    if templates:
        stmt = stmt.where(ApprovalRoute.template.in_([t.value for t in templates]))
    stmt = paging.apply(stmt, ApprovalRoute.created_at, ApprovalRoute.id, decode_cursor(cursor), limit)
    rows = list((await session.execute(stmt)).scalars().all())
    page, next_cursor = paging.cut(rows, limit, lambda r: r.created_at, lambda r: r.id)
    documents = {
        d.id: d
        for d in (
            await session.execute(
                select(Document).where(Document.id.in_([r.document_id for r in page if r.document_id]))
            )
        ).scalars()
    }
    current_steps = {
        (s.approval_id, s.index): s
        for s in (
            await session.execute(
                select(ApprovalStep).where(
                    ApprovalStep.approval_id.in_([r.id for r in page]), ApprovalStep.status == "current"
                )
            )
        ).scalars()
    }
    directory = Directory()
    items = [
        ApprovalListItem(
            id=r.id,
            template=ApprovalTemplate(r.template),
            title=r.title,
            object=object_of(r, documents.get(r.document_id) if r.document_id else None),
            status=RouteStatus(r.status),
            round=r.round,
            current_step=step_of(current_steps[(r.id, r.current_step)], directory)
            if r.current_step is not None and (r.id, r.current_step) in current_steps
            else None,
            created_at=r.created_at,
        )
        for r in page
    ]
    return ApprovalPage(items=items, next_cursor=next_cursor)
