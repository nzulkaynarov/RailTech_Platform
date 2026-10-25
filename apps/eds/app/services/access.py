"""Видимость объектов сотруднику (правила eds.yaml): без `registry.read` — свои документы и маршруты, где участник.

Участник маршрута — тот, кого ждёт какой-либо шаг (назначен по `crm_user_id` или держит право шага) либо кто уже
решил шаг. Автор документа видит его всегда. Чужой объект для сотрудника — `404`, существование не раскрывается.
"""

import uuid

from sqlalchemy import ColumnElement, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApprovalRoute, ApprovalStep, Document, Employee
from app.security.permissions import EdsPermission, known_permissions


def has(employee: Employee, permission: EdsPermission) -> bool:
    return permission.value in known_permissions(employee.permissions_eds)


def step_is_mine(employee: Employee) -> ColumnElement[bool]:
    """Шаг ждёт этого сотрудника: назначен ему или он держит право шага."""
    return or_(
        ApprovalStep.assignee_crm_user_id == employee.crm_user_id,
        ApprovalStep.assignee_permission.in_(known_permissions(employee.permissions_eds)),
    )


def participates_in(employee: Employee) -> ColumnElement[bool]:
    """Строка шага связывает сотрудника с маршрутом: ждали его или он решил."""
    return or_(step_is_mine(employee), ApprovalStep.decided_by == employee.crm_user_id)


def document_visible(employee: Employee) -> ColumnElement[bool]:
    """Условие видимости для запроса по `Document`."""
    if has(employee, EdsPermission.REGISTRY_READ):
        return true()
    in_route = exists(
        select(1)
        .select_from(ApprovalStep)
        .join(ApprovalRoute, ApprovalRoute.id == ApprovalStep.approval_id)
        .where(ApprovalRoute.document_id == Document.id, participates_in(employee))
    )
    return or_(Document.author_crm_user_id == employee.crm_user_id, in_route)


def route_visible(employee: Employee) -> ColumnElement[bool]:
    """Условие видимости для запроса по `ApprovalRoute` (автор документа, участник, `registry.read`)."""
    if has(employee, EdsPermission.REGISTRY_READ):
        return true()
    in_route = exists(select(1).where(ApprovalStep.approval_id == ApprovalRoute.id, participates_in(employee)))
    own_document = exists(
        select(1).where(Document.id == ApprovalRoute.document_id, Document.author_crm_user_id == employee.crm_user_id)
    )
    return or_(in_route, own_document)


async def can_view_document(session: AsyncSession, employee: Employee, document_id: uuid.UUID) -> bool:
    row = await session.execute(select(Document.id).where(Document.id == document_id, document_visible(employee)))
    return row.scalar_one_or_none() is not None


async def can_view_route(session: AsyncSession, employee: Employee, route_id: uuid.UUID) -> bool:
    row = await session.execute(select(ApprovalRoute.id).where(ApprovalRoute.id == route_id, route_visible(employee)))
    return row.scalar_one_or_none() is not None


def can_read_letters(employee: Employee) -> bool:
    return has(employee, EdsPermission.LETTERS_READ)


__all__ = [
    "can_read_letters",
    "can_view_document",
    "can_view_route",
    "document_visible",
    "has",
    "participates_in",
    "route_visible",
    "step_is_mine",
]
