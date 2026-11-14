"""Подпись официальных коммерческих документов ERP (SIGN-4, ADR-0024 п. 3, 7).

`erp.signing.requested` открывает маршрут с одним шагом «Подписать» на уполномоченного сотрудника: сам запрос ничего не
подписывает. Решение принимает живой сотрудник; перед подписью полномочие проверяется ещё раз на день подписи. Итог —
`eds.signing.decided` (signed или rejected с причиной) и строка журнала.

Одна версия документа подписывается один раз: повтор открытого запроса ничего не делает, запрос уже подписанной версии
отклоняется, новая версия закрывает открытый круг прежней.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import structlog
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import any_, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.bus.erp_snapshots import SigningRequestedEvent
from app.config import get_settings
from app.errors import conflict
from app.models import ApprovalRoute, ApprovalStep, Employee
from app.schemas.approvals import ApprovalTemplate, Decision, DecisionIn, RouteStatus
from app.security.permissions import EdsPermission
from app.services import approvals, documents, events, journal, signing_resolve

log = structlog.get_logger(__name__)

SIGN_LABEL = "Подписать"
_TITLES = {"quote": "КП", "contract": "Договор", "invoice": "Счёт", "act": "Акт"}

#: ADR-0025: визы перед подписью по виду документа — (подпись шага, право EDS, роль словами для причины отказа).
#: Первая версия данных маршрута; состав настраивается в шаблоне документа (план маршрутов, партия 3).
FINANCE_VISA = ("Виза бухгалтера", EdsPermission.APPROVALS_VISA_FINANCE.value, "Бухгалтер")
LEGAL_VISA = ("Виза юриста", EdsPermission.APPROVALS_VISA_LEGAL.value, "Юрист")
DOCUMENT_VISAS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "contract": (FINANCE_VISA, LEGAL_VISA),
    "invoice": (FINANCE_VISA,),
    "act": (FINANCE_VISA,),
}
VISA_PERMISSIONS = frozenset(permission for _, permission, _ in (FINANCE_VISA, LEGAL_VISA))


async def _missing_visa_role(session: AsyncSession, kind: str) -> str | None:
    """Роль визы, у которой нет ни одного активного держателя права (правило владельца 13): маршрут не стартует."""
    for _, permission, role in DOCUMENT_VISAS.get(kind, ()):
        holder = await session.scalar(
            select(Employee.crm_user_id)
            .where(Employee.is_active.is_(True), literal(permission) == any_(Employee.permissions_eds))
            .limit(1)
        )
        if holder is None:
            return role
    return None


def _object_ref(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": snap["kind"],
        "object_id": snap["object_id"],
        "number": snap["number"],
        "version": snap.get("version"),
    }


def _amount(snap: dict[str, Any]) -> Decimal | None:
    tiyins = snap.get("amount_tiyins")
    return Decimal(tiyins) / Decimal(100) if tiyins is not None else None


async def _publish_rejected(
    session: AsyncSession, bus: AsyncBus, snap: dict[str, Any], signer: dict[str, Any], comment: str, by: int | None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "object": _object_ref(snap),
        "decision": "rejected",
        "signer": signer,
        "authority_id": None,
        "basis": None,
        "basis_text": None,
        "verification_code": None,
        "verification_url": None,
        "signed_at": None,
        "comment": comment,
        "actor": events.actor(by),
    }
    await events.publish(bus, session, "signing.decided", data, subject=snap["number"])
    await journal.record(
        session,
        "commercial_signing.rejected",
        by=by,
        comment=f"Отказ в подписи {snap['kind']} № {snap['number']}: {comment}",
    )
    log.warning("commercial_signing_rejected", kind=snap["kind"], number=snap["number"], reason=comment)
    return data


async def _routes_of(session: AsyncSession, snap: dict[str, Any]) -> list[ApprovalRoute]:
    rows = await session.execute(
        select(ApprovalRoute)
        .where(
            ApprovalRoute.template == ApprovalTemplate.SIGNING.value,
            ApprovalRoute.signing_snapshot["kind"].astext == snap["kind"],
            ApprovalRoute.signing_snapshot["object_id"].astext == str(snap["object_id"]),
        )
        .with_for_update()
    )
    return list(rows.scalars())


async def _supersede(session: AsyncSession, route: ApprovalRoute, version: int | None) -> None:
    for step in await approvals.load_steps(session, route.id):
        if step.status in ("current", "pending"):
            step.status = "skipped"
    route.status, route.current_step, route.closed_at = RouteStatus.RETURNED.value, None, clock.now()
    await journal.record(
        session,
        "approval.superseded",
        by=None,
        approval_id=route.id,
        comment=f"заменён версией {version}",
        version=route.round,
    )


#: Final ERP statuses of a project document (`project_documents.source_of`): nobody signs it any more (FR-30).
FINAL_STATUSES: dict[str, frozenset[str]] = {
    "contract": frozenset({"signed", "rejected", "cancelled"}),
    "act": frozenset({"signed"}),
}


async def withdraw_finished(session: AsyncSession, kind: str, erp_id: int, status: str) -> int:
    """Plan 0.7 (FR-30): the document was signed, accepted or cancelled in ERP — its open «Sign» route closes.

    Otherwise the signer keeps «Ждут вашей подписи» for a document that is already done. Idempotent: a closed route is
    not touched; returns how many routes were closed.
    """
    if status not in FINAL_STATUSES.get(kind, frozenset()):
        return 0
    closed = 0
    for route in await _routes_of(session, {"kind": kind, "object_id": erp_id}):
        if route.status != RouteStatus.OPEN.value:
            continue
        for step in await approvals.load_steps(session, route.id):
            if step.status in ("current", "pending"):
                step.status = "skipped"
        route.status, route.current_step, route.closed_at = RouteStatus.RETURNED.value, None, clock.now()
        await journal.record(
            session,
            "approval.withdrawn",
            by=None,
            approval_id=route.id,
            comment=f"{_TITLES.get(kind, kind)} уже в статусе «{status}» в ERP — подпись не нужна",
            version=route.round,
        )
        closed += 1
    if closed:
        log.info("commercial_signing_withdrawn", kind=kind, erp_id=erp_id, status=status, routes=closed)
    return closed


async def handle_signing_request(
    session: AsyncSession,
    bus: AsyncBus,
    data: SigningRequestedEvent,
    *,
    event_time: dt.datetime | None = None,
) -> dict[str, Any]:
    """Запрос подписи от ERP: открыть шаг «Подписать» или сразу отказать, если подписать некому."""
    obj = data.object
    snap: dict[str, Any] = {
        "kind": obj.kind,
        "object_id": obj.object_id,
        "number": obj.number,
        "version": obj.version,
        "amount_tiyins": obj.amount_tiyins,
        "currency": obj.currency,
        "title": obj.title,
        "deal_id": obj.deal_id,
        "requested_by": data.requested_by.crm_user_id,
    }
    routes = await _routes_of(session, snap)
    same_version = [route for route in routes if (route.signing_snapshot or {}).get("version") == obj.version]
    if any(route.status == RouteStatus.OPEN.value for route in same_version):
        log.info("commercial_signing_duplicate", kind=obj.kind, number=obj.number, version=obj.version)
        return {"decision": "pending"}

    person = data.requested_signer or data.requested_by
    fallback = {"crm_user_id": person.crm_user_id, "full_name": person.name, "position": person.position}
    if any(route.status == RouteStatus.APPROVED.value for route in same_version):
        return await _publish_rejected(session, bus, snap, fallback, "Эта версия документа уже подписана.", None)

    for route in routes:
        if route.status == RouteStatus.OPEN.value:
            await _supersede(session, route, obj.version)

    today = event_time.date() if event_time else clock.now().date()
    amount = _amount(snap)
    resolution = await signing_resolve.resolve(
        session, kind=obj.kind, amount=amount, currency=obj.currency, on_date=today
    )
    if data.requested_signer is not None:
        check = signing_resolve.signer_check(resolution, data.requested_signer.crm_user_id)
        if not (check.allowed and check.candidate):
            return await _publish_rejected(
                session, bus, snap, fallback, check.message or "Нет полномочий подписать документ.", None
            )
        signer_id = check.candidate.signer.crm_user_id
    elif resolution.candidates:
        signer_id = resolution.candidates[0].signer.crm_user_id
    else:
        return await _publish_rejected(
            session,
            bus,
            snap,
            fallback,
            "Нет сотрудника с полномочием подписать этот документ. Проверьте реестр.",
            None,
        )

    missing = await _missing_visa_role(session, obj.kind)
    if missing is not None:
        return await _publish_rejected(
            session,
            bus,
            snap,
            fallback,
            f"Нет сотрудника с ролью «{missing}»: назначьте её в «Ролях и правах», затем отправьте на подпись снова.",
            None,
        )

    # ADR-0025: визы по должности, затем «Подписать»; виза инициатора — строкой журнала, без шага.
    visas = [
        approvals.StepSpec(label, permission=permission) for label, permission, _ in DOCUMENT_VISAS.get(obj.kind, ())
    ]
    route = await approvals.open_route(
        session,
        bus,
        template=ApprovalTemplate.SIGNING,
        title=f"{_TITLES.get(obj.kind, obj.kind)} {obj.number}",
        steps=[*visas, approvals.StepSpec(SIGN_LABEL, crm_user_id=signer_id)],
        actor_id=data.requested_by.crm_user_id,
        round_no=len(routes) + 1,
        fields={"signing_snapshot": snap, "erp_deal_id": obj.deal_id},
    )
    await journal.record(
        session,
        "approval.initiator_visa",
        by=data.requested_by.crm_user_id,
        approval_id=route.id,
        comment=f"Инициатор {data.requested_by.name} согласовал, отправив на подпись",
        version=route.round,
    )
    log.info("commercial_signing_requested", kind=obj.kind, number=obj.number, route=str(route.id), signer=signer_id)
    return {"decision": "pending", "route": str(route.id)}


async def decide(
    session: AsyncSession,
    bus: AsyncBus,
    employee: Employee,
    route: ApprovalRoute,
    steps: list[ApprovalStep],
    current: ApprovalStep,
    body: DecisionIn,
) -> ApprovalRoute:
    """Виза (ADR-0025) или «Подписать»: подпись — только при действующем полномочии; отказ и возврат уходят автору
    с причиной."""
    snap = route.signing_snapshot or {}
    now = clock.now()
    if current.assignee_permission in VISA_PERMISSIONS:
        result = await approvals.complete_step(session, bus, employee, route, steps, current, body)
        if body.decision is not Decision.APPROVE:
            # Несогласие останавливает круг (правило владельца 7): ERP получает отказ с замечанием визирующего.
            visa = {
                "crm_user_id": employee.crm_user_id,
                "full_name": employee.full_name,
                "position": employee.position or "",
            }
            note = f"{current.label}: {body.comment or 'возвращено с замечанием'}"
            await _publish_rejected(session, bus, snap, visa, note, employee.crm_user_id)
        return result
    if body.decision is not Decision.APPROVE:
        result = await approvals.complete_step(session, bus, employee, route, steps, current, body)
        signer = {
            "crm_user_id": employee.crm_user_id,
            "full_name": employee.full_name,
            "position": employee.position or "",
        }
        await _publish_rejected(session, bus, snap, signer, body.comment or "Отказ", employee.crm_user_id)
        return result

    check = await signing_resolve.check_signer(
        session,
        employee.crm_user_id,
        kind=snap["kind"],
        amount=_amount(snap),
        currency=snap.get("currency"),
        on_date=now.date(),
    )
    if not (check.allowed and check.candidate):
        raise conflict("no_signing_authority", check.message or "Нет действующего полномочия на подпись.")

    result = await approvals.complete_step(session, bus, employee, route, steps, current, body)
    candidate = check.candidate
    code = documents.generate_verification_code()
    data = {
        "object": _object_ref(snap),
        "decision": "signed",
        "signer": {
            "crm_user_id": candidate.signer.crm_user_id,
            "full_name": candidate.signer.full_name,
            "position": candidate.position or employee.position or "",
        },
        "authority_id": str(candidate.authority.id),
        "basis": candidate.authority.basis,
        "basis_text": candidate.basis_text,
        "verification_code": code,
        "verification_url": f"https://{get_settings().cabinet_domain}/v/{code}",
        "signed_at": now.isoformat(),
        "comment": None,
        "actor": events.actor(employee.crm_user_id),
    }
    await events.publish(bus, session, "signing.decided", data, subject=snap["number"])
    await journal.record(
        session,
        "commercial_signing.signed",
        by=employee.crm_user_id,
        approval_id=route.id,
        comment=f"Документ {snap['kind']} № {snap['number']} подписан. Код: {code}",
    )
    log.info("commercial_signing_signed", kind=snap["kind"], number=snap["number"], signer=employee.crm_user_id)
    return result
