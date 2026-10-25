"""Движок маршрутов согласования (runbook волны 12 §2.5; eds.yaml, тег `approvals`).

Маршрут — один круг: упорядоченные шаги «кто решает» (конкретный сотрудник или любой с правом). Шаблоны v1:
служебная записка — директор (`memos.approve`), затем бухгалтер (`payments.confirm`), если указана сумма;
КП — директор (`approvals.decide`) с чек-листом; заявление и отчёт — директор. Решения `approve`, `return`
(автор правит и отправляет снова — новый круг и новая версия документа), `reject`. Каждое решение — строка журнала и
событие `approval.decided`; открытие — `approval.requested`. Маршрут не знает коммерческого содержания: данные КП —
снимок из события, только для показа.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import conflict, forbidden_reason, not_found
from app.models import ApprovalRoute, ApprovalStep, Document, Employee
from app.schemas.approvals import ApprovalTemplate, Decision, DecisionIn, RouteStatus
from app.security.permissions import EdsPermission as P
from app.security.permissions import known_permissions
from app.services import access, checklist, document_state, events, journal, numbering
from app.services.people import load_directory

DIRECTOR = "Директор"
ACCOUNTANT = "Бухгалтер"
_STEP_STATUS = {Decision.APPROVE: "approved", Decision.RETURN: "returned", Decision.REJECT: "rejected"}
_ROUTE_STATUS = {
    Decision.APPROVE: RouteStatus.APPROVED,
    Decision.RETURN: RouteStatus.RETURNED,
    Decision.REJECT: RouteStatus.REJECTED,
}


@dataclass(frozen=True)
class StepSpec:
    """Шаг шаблона: ровно одно из `crm_user_id` и `permission`."""

    label: str
    crm_user_id: int | None = None
    permission: str | None = None


def steps_for(template: ApprovalTemplate, *, addressee: int | None = None, with_amount: bool = False) -> list[StepSpec]:
    """Шаги шаблона v1. `addressee` — конкретный адресат вместо «любого с правом» первого шага."""
    if template is ApprovalTemplate.QUOTE:
        return [StepSpec(DIRECTOR, permission=P.APPROVALS_DECIDE.value)]
    director = (
        StepSpec(DIRECTOR, crm_user_id=addressee) if addressee else StepSpec(DIRECTOR, permission=P.MEMOS_APPROVE.value)
    )
    if template is ApprovalTemplate.MEMO and with_amount:
        return [director, StepSpec(ACCOUNTANT, permission=P.PAYMENTS_CONFIRM.value)]
    return [director]


def assignee_dict(step: ApprovalStep | StepSpec) -> dict[str, Any]:
    if isinstance(step, ApprovalStep):
        return {"crm_user_id": step.assignee_crm_user_id, "permission": step.assignee_permission}
    return {"crm_user_id": step.crm_user_id, "permission": step.permission}


def is_mine(step: ApprovalStep, employee: Employee) -> bool:
    """Шаг ждёт сотрудника: назначен ему или он держит право шага."""
    if step.assignee_crm_user_id is not None:
        return step.assignee_crm_user_id == employee.crm_user_id
    return step.assignee_permission in known_permissions(employee.permissions_eds)


async def load_steps(session: AsyncSession, route_id: uuid.UUID) -> list[ApprovalStep]:
    rows = await session.execute(
        select(ApprovalStep).where(ApprovalStep.approval_id == route_id).order_by(ApprovalStep.index)
    )
    return list(rows.scalars().all())


def object_ref(route: ApprovalRoute, document: Document | None) -> dict[str, Any]:
    """`ApprovalObject` события: документ EDS или КП ERP (коммерческое содержание остаётся в ERP)."""
    if route.template == ApprovalTemplate.QUOTE.value:
        return {
            "kind": "quote",
            "erp_quote_id": route.erp_quote_id,
            "quote_number": route.quote_number,
            "quote_version": route.quote_version,
            "erp_deal_id": route.erp_deal_id,
            "deal_number": route.deal_number,
        }
    if document is None or document.number is None:
        raise RuntimeError("маршрут документа открывается только для документа с номером реестра")
    return {"kind": route.template, "eds_document_id": str(document.id), "number": document.number}


def approval_ref(route: ApprovalRoute, document: Document | None) -> dict[str, Any]:
    return {
        "eds_approval_id": str(route.id),
        "template": route.template,
        "object": object_ref(route, document),
        "title": route.title,
    }


def _subject(route: ApprovalRoute, document: Document | None) -> str:
    return (route.quote_number if document is None else document.number) or str(route.id)


async def open_route(
    session: AsyncSession,
    bus: AsyncBus,
    *,
    template: ApprovalTemplate,
    title: str,
    steps: list[StepSpec],
    actor_id: int | None,
    round_no: int = 1,
    document: Document | None = None,
    fields: dict[str, Any] | None = None,
) -> ApprovalRoute:
    """Открыть круг: маршрут, шаги (первый — текущий), журнал и `approval.requested` — в транзакции вызывающего."""
    route = ApprovalRoute(
        id=uuid.uuid4(),
        template=template.value,
        title=title[:300],
        status=RouteStatus.OPEN.value,
        round=round_no,
        current_step=1,
        document_id=document.id if document else None,
        created_at=clock.now(),
        **(fields or {}),
    )
    session.add(route)
    await session.flush()
    for index, spec in enumerate(steps, start=1):
        session.add(
            ApprovalStep(
                approval_id=route.id,
                index=index,
                label=spec.label,
                assignee_crm_user_id=spec.crm_user_id,
                assignee_permission=spec.permission,
                status="current" if index == 1 else "pending",
            )
        )
    await session.flush()
    await journal.record(
        session,
        "approval.requested",
        by=actor_id,
        approval_id=route.id,
        document_id=route.document_id,
        version=round_no,
    )
    data = {
        "approval": approval_ref(route, document),
        "step": {"index": 1, "assignee": assignee_dict(steps[0])},
        "actor": events.actor(actor_id),
    }
    await events.publish(bus, session, "approval.requested", data, subject=_subject(route, document))
    return route


async def get_for_decision(session: AsyncSession, route_id: uuid.UUID) -> ApprovalRoute:
    stmt = select(ApprovalRoute).where(ApprovalRoute.id == route_id).with_for_update()
    route = (await session.execute(stmt)).scalar_one_or_none()
    if route is None:
        raise not_found("Маршрут не найден.")
    return route


async def decide(
    session: AsyncSession, bus: AsyncBus, *, employee: Employee, route_id: uuid.UUID, body: DecisionIn
) -> ApprovalRoute:
    """Решение на текущем шаге. Порядок отказов: не виден → 404; закрыт → 409 `route_closed`; не ваш шаг → 403
    `not_your_step`; чек-лист КП красный → 409 `checklist_not_green` (проверка на сервере)."""
    route = await get_for_decision(session, route_id)
    if not await access.can_view_route(session, employee, route.id):
        raise not_found("Маршрут не найден.")
    if route.status != RouteStatus.OPEN.value:
        raise conflict("route_closed", "Маршрут уже завершён.", status=route.status)
    steps = await load_steps(session, route.id)
    current = next(s for s in steps if s.index == route.current_step)
    if not is_mine(current, employee):
        raise forbidden_reason("not_your_step", "Сейчас решение за другим сотрудником.")
    if route.template == ApprovalTemplate.QUOTE.value and body.decision is Decision.APPROVE:
        await _require_green(session, route)
    return await _apply(session, bus, employee, route, steps, current, body)


async def _require_green(session: AsyncSession, route: ApprovalRoute) -> None:
    items = checklist.build(route.quote_snapshot or {}, await checklist.resolution_threshold(session, route))
    if not checklist.is_green(items):
        failed = [item.code for item in items if not item.ok]
        raise conflict("checklist_not_green", "Чек-лист КП не выполнен: одобрение недоступно.", failed=failed)


async def _apply(
    session: AsyncSession,
    bus: AsyncBus,
    employee: Employee,
    route: ApprovalRoute,
    steps: list[ApprovalStep],
    current: ApprovalStep,
    body: DecisionIn,
) -> ApprovalRoute:
    now = clock.now()
    decision = body.decision
    current.status, current.decided_by, current.decided_at, current.comment = (
        _STEP_STATUS[decision],
        employee.crm_user_id,
        now,
        body.comment,
    )
    following = next((s for s in steps if s.index > current.index), None)
    if decision is Decision.APPROVE and following is not None:
        following.status, route.current_step = "current", following.index
        route_status = RouteStatus.OPEN
    else:
        route_status = _ROUTE_STATUS[decision]
        route.status, route.current_step, route.closed_at = route_status.value, None, now
    channels = [c.value for c in body.channels] if body.channels is not None else None
    if route.template == ApprovalTemplate.QUOTE.value and route_status is RouteStatus.APPROVED:
        route.outgoing_number = await numbering.allocate(session, numbering.NumberKind.OUTGOING, now)
        route.channels = channels
    document = None
    if route.document_id is not None:
        document = (
            await session.execute(select(Document).where(Document.id == route.document_id).with_for_update())
        ).scalar_one()
    await journal.record(
        session,
        "approval.decided",
        by=employee.crm_user_id,
        approval_id=route.id,
        document_id=route.document_id,
        comment=body.comment,
        version=route.round,
    )
    await _publish_decided(session, bus, employee, route, document, current, body, route_status, now)
    if document is not None:  # статус документа и архив — после решения: события идут в порядке причин
        await document_state.apply_decision(
            session,
            bus,
            document,
            decision=decision,
            last_step=following is None,
            with_accountant=len(steps) > 1,
            actor_id=employee.crm_user_id,
        )
    return route


async def _publish_decided(
    session: AsyncSession,
    bus: AsyncBus,
    employee: Employee,
    route: ApprovalRoute,
    document: Document | None,
    step: ApprovalStep,
    body: DecisionIn,
    route_status: RouteStatus,
    decided_at: datetime,
) -> None:
    directory = await load_directory(session, [employee.crm_user_id])
    data: dict[str, Any] = {
        "approval": approval_ref(route, document),
        "step": {"index": step.index, "assignee": assignee_dict(step)},
        "decision": body.decision.value,
        "comment": body.comment,
        "decided_by": directory.person(employee.crm_user_id).model_dump(),
        "decided_at": decided_at.isoformat(),
        "route_status": route_status.value,
        "outgoing_number": route.outgoing_number,
        "actor": events.actor(employee.crm_user_id),
    }
    if route.channels is not None and route.outgoing_number is not None:
        data["channels"] = route.channels
    await events.publish(bus, session, "approval.decided", data, subject=_subject(route, document))
