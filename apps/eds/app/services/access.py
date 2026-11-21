"""Видимость объектов сотруднику (правила eds.yaml): без `registry.read` — свои документы и маршруты, где участник.

Участник маршрута — тот, кого ждёт какой-либо шаг (назначен по `crm_user_id` или держит право шага) либо кто уже
решил шаг. Автор документа видит его всегда. Чужой объект для сотрудника — `404`, существование не раскрывается.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, and_, any_, exists, literal, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app import clock
from app.models import ApprovalRoute, ApprovalStep, Document, Employee
from app.security.permissions import EdsPermission, known_permissions

# --- замещение (СЦ-9 P11, решение владельца 2026-11-21 (2)) -----------------------------------------------------------
# Заместитель на период решает шаги замещаемого: служебки, заявления, отчёты, КП, поручения и переносы срока. Подпись
# (решение 2026-11-05, ADR-0024 п. 2) и подтверждение оплаты не переходят: у них своё полномочие и свой экран.
DEPUTY_TEMPLATE_BLOCKED = "signing"
DEPUTY_PERMISSION_BLOCKED = EdsPermission.PAYMENTS_CONFIRM.value
DEPUTY_PERMISSIONS = (EdsPermission.MEMOS_APPROVE.value, EdsPermission.APPROVALS_DECIDE.value)
INSTRUCTION = "instruction"  # вид шага «поручение или перенос срока» для `acting_on_behalf`


def deputy_today() -> date:
    return clock.company_date(clock.now())


@dataclass(frozen=True)
class Acting:
    """Ответ «от чьего имени сотрудник вправе действовать на шаге»: `allowed` и, если не за себя, замещаемый."""

    allowed: bool
    on_behalf_of: Employee | None = None


REFUSED = Acting(False)
SELF = Acting(True)


def _kind_transferable(template: str | None, permission: str | None) -> bool:
    return template != DEPUTY_TEMPLATE_BLOCKED and permission != DEPUTY_PERMISSION_BLOCKED


async def covered_employees(session: AsyncSession, employee: Employee, today: date | None = None) -> list[Employee]:
    """Активные сотрудники, которых `employee` сегодня замещает (период включительно, дата компании)."""
    day = today or deputy_today()
    rows = await session.execute(
        select(Employee)
        .where(
            Employee.deputy_crm_user_id == employee.crm_user_id,
            Employee.is_active.is_(True),
            Employee.deputy_from <= day,
            Employee.deputy_to >= day,
        )
        .order_by(Employee.crm_user_id)
    )
    return list(rows.scalars().all())


async def acting_on_behalf(
    session: AsyncSession,
    employee: Employee,
    *,
    owner: int | None = None,
    permission: str | None = None,
    template: str | None = None,
    today: date | None = None,
    covered: list[Employee] | None = None,
) -> Acting:
    """Единая точка: от чьего имени `employee` вправе решить шаг сегодня.

    Шаг задан исполнителем (`owner`, crm_user_id) или правом (`permission`); `template` — вид маршрута (`signing`) или
    `INSTRUCTION`. Себя — если шаг его; иначе замещаемый, чей шаг это и чей вид шага переходит. Подпись и оплата —
    отказ всегда. `covered` — заранее загруженный список замещаемых (для списков, без запроса на строку).
    """
    if owner == employee.crm_user_id or (
        permission is not None and permission in known_permissions(employee.permissions_eds)
    ):
        return SELF
    if not _kind_transferable(template, permission):
        return REFUSED
    for replaced in covered if covered is not None else await covered_employees(session, employee, today):
        if owner is not None and owner == replaced.crm_user_id:
            return Acting(True, replaced)
        if (
            permission is not None
            and permission in DEPUTY_PERMISSIONS
            and permission in known_permissions(replaced.permissions_eds)
        ):
            return Acting(True, replaced)
    return REFUSED


def has(employee: Employee, permission: EdsPermission) -> bool:
    return permission.value in known_permissions(employee.permissions_eds)


def _deputy_step(employee: Employee) -> ColumnElement[bool]:
    """Шаг замещаемого, который решает заместитель (зеркало `acting_on_behalf`): не подпись и не оплата."""
    replaced = aliased(Employee)
    today = deputy_today()
    route, document = aliased(ApprovalRoute), aliased(Document)
    foreign_own = (
        select(1)
        .where(document.id == route.document_id, document.author_crm_user_id == replaced.crm_user_id)
        .correlate(route, replaced)
    )
    # документ замещаемого решает он сам или никто: заместитель не решает «свою» служебку за него
    transferable_route = (
        select(route.id).where(route.template != DEPUTY_TEMPLATE_BLOCKED, ~exists(foreign_own)).correlate(replaced)
    )
    return exists(
        select(1).where(
            replaced.deputy_crm_user_id == employee.crm_user_id,
            replaced.is_active.is_(True),
            replaced.deputy_from <= today,
            replaced.deputy_to >= today,
            ApprovalStep.approval_id.in_(transferable_route),
            or_(
                ApprovalStep.assignee_crm_user_id == replaced.crm_user_id,
                and_(
                    ApprovalStep.assignee_permission.in_(DEPUTY_PERMISSIONS),
                    ApprovalStep.assignee_permission == any_(replaced.permissions_eds),
                ),
            ),
        )
    )


def step_is_mine(employee: Employee) -> ColumnElement[bool]:
    """Шаг ждёт этого сотрудника: назначен ему, он держит право шага или он замещает того, кому шаг назначен."""
    return or_(
        ApprovalStep.assignee_crm_user_id == employee.crm_user_id,
        ApprovalStep.assignee_permission.in_(known_permissions(employee.permissions_eds)),
        _deputy_step(employee),
    )


def step_open_to(employee: Employee) -> ColumnElement[bool]:
    """Шаг вправе решить сотрудник: он «мой» и это не разделение обязанностей наоборот.

    Автор документа не решает шаг по своему документу, если есть кому другому: шаг на него самого — никогда;
    шаг «любой с правом X» — пока в проекции есть другой активный держатель X. Единственный держатель (директор
    без заместителя) решает свои документы сам. Для КП автора нет — ограничение не действует.
    """
    own_document = exists(
        select(1).where(Document.id == ApprovalRoute.document_id, Document.author_crm_user_id == employee.crm_user_id)
    )
    other_holder = exists(
        select(1).where(
            Employee.is_active.is_(True),
            Employee.crm_user_id != employee.crm_user_id,
            ApprovalStep.assignee_permission == any_(Employee.permissions_eds),
        )
    )
    blocked = and_(own_document, or_(ApprovalStep.assignee_crm_user_id.is_not(None), other_holder))
    return and_(step_is_mine(employee), not_(blocked))


def participates_in(employee: Employee) -> ColumnElement[bool]:
    """Строка шага связывает сотрудника с маршрутом: ждали его или он решил."""
    return or_(step_is_mine(employee), ApprovalStep.decided_by == employee.crm_user_id)


def document_visible(employee: Employee) -> ColumnElement[bool]:
    """Условие видимости для запроса по `Document` — один предикат для реестра, `/documents`, карточки и файлов (D1-10).

    Не шире прав на вид документа, даже у держателя `registry.read`: чужой черновик (`draft`) видит только автор
    (черновик письма, переданный на регистрацию, — ещё держатель `letters.register`), чужое исходящее письмо
    (`letter_out`) — только с `letters.read`. Дальше: `registry.read` — остальное видно, иначе — автор, участник
    маршрута, получатель копии (пункт 1.6) или делопроизводитель переданного ему письма.
    """
    mine = Document.author_crm_user_id == employee.crm_user_id
    # P4, B-P8B-4: черновик письма, переданный на регистрацию, видит держатель `letters.register`.
    handed_over = (
        and_(Document.kind == "letter_out", Document.registration_requested_at.is_not(None))
        if has(employee, EdsPermission.LETTERS_REGISTER)
        else literal(False)
    )
    not_foreign_draft = or_(Document.status != "draft", mine, handed_over)
    # Своё письмо автор видит и без `letters.read` (исполнитель готовит ответ, P4).
    letters_ok = true() if can_read_letters(employee) else or_(Document.kind != "letter_out", mine)
    base = and_(not_foreign_draft, letters_ok)
    if has(employee, EdsPermission.REGISTRY_READ):
        return base
    in_route = exists(
        select(1)
        .select_from(ApprovalStep)
        .join(ApprovalRoute, ApprovalRoute.id == ApprovalStep.approval_id)
        .where(ApprovalRoute.document_id == Document.id, participates_in(employee))
    )
    # Пункт 1.6: получатель копии видит документ (не решает).
    watching = Document.watchers.contains([employee.crm_user_id])
    return and_(base, or_(mine, in_route, handed_over, watching))


def route_visible(employee: Employee) -> ColumnElement[bool]:
    """Условие видимости для запроса по `ApprovalRoute` (D1-10).

    Участник маршрута видит его всегда (он должен видеть, что согласует). Остальные — маршрут документа, только если
    им виден сам документ (`document_visible`: например, маршрут исходящего письма без `letters.read` скрыт даже при
    `registry.read`); маршрут без документа (КП) — с `registry.read`.
    """
    participant = exists(select(1).where(ApprovalStep.approval_id == ApprovalRoute.id, participates_in(employee)))
    document_seen = exists(
        select(1).where(Document.id == ApprovalRoute.document_id, document_visible(employee)),
    )
    quote_seen = and_(ApprovalRoute.document_id.is_(None), literal(has(employee, EdsPermission.REGISTRY_READ)))
    return or_(participant, document_seen, quote_seen)


async def can_view_document(session: AsyncSession, employee: Employee, document_id: uuid.UUID) -> bool:
    row = await session.execute(select(Document.id).where(Document.id == document_id, document_visible(employee)))
    return row.scalar_one_or_none() is not None


async def can_view_route(session: AsyncSession, employee: Employee, route_id: uuid.UUID) -> bool:
    row = await session.execute(select(ApprovalRoute.id).where(ApprovalRoute.id == route_id, route_visible(employee)))
    return row.scalar_one_or_none() is not None


def can_read_letters(employee: Employee) -> bool:
    return has(employee, EdsPermission.LETTERS_READ)


def can_read_project_documents(employee: Employee) -> bool:
    """Договоры, счета и акты проектов (проекция ERP, D2-5) видит держатель `registry.read`; остальным их нет совсем."""
    return has(employee, EdsPermission.REGISTRY_READ)


__all__ = [
    "INSTRUCTION",
    "REFUSED",
    "SELF",
    "Acting",
    "acting_on_behalf",
    "can_read_letters",
    "can_read_project_documents",
    "can_view_document",
    "can_view_route",
    "covered_employees",
    "document_visible",
    "has",
    "participates_in",
    "route_visible",
    "step_is_mine",
    "step_open_to",
]
