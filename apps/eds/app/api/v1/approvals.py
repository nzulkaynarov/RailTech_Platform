"""Маршруты согласования: `/api/v1/approvals…` (eds.yaml, тег `approvals`); движок — `services/approvals.py`."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bus, get_session, require_permission
from app.models import Employee
from app.schemas.approvals import Approval, ApprovalPage, ApprovalTemplate, DecisionIn, RouteStatus
from app.schemas.pagination import Cursor, Limit
from app.security.permissions import EdsPermission as P
from app.services import approvals, approvals_read

router = APIRouter(prefix="/api/v1", tags=["approvals"])

Reader = Annotated[
    Employee,
    Depends(
        require_permission(P.MEMOS_CREATE, P.MEMOS_APPROVE, P.APPROVALS_DECIDE, P.PAYMENTS_CONFIRM, P.REGISTRY_READ)
    ),
]
Decider = Annotated[Employee, Depends(require_permission(P.MEMOS_APPROVE, P.APPROVALS_DECIDE, P.PAYMENTS_CONFIRM))]
Session = Annotated[AsyncSession, Depends(get_session)]
Bus = Annotated[AsyncBus, Depends(get_bus)]


@router.get("/approvals", response_model=ApprovalPage, operation_id="listApprovals")
async def list_approvals(
    employee: Reader,
    session: Session,
    mine: bool = True,
    status: Annotated[list[RouteStatus] | None, Query()] = None,
    template: Annotated[list[ApprovalTemplate] | None, Query()] = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> ApprovalPage:
    return await approvals_read.list_page(
        session, employee, mine=mine, statuses=status, templates=template, cursor=cursor, limit=limit
    )


@router.get("/approvals/{approval_id}", response_model=Approval, operation_id="getApproval")
async def get_approval(approval_id: uuid.UUID, employee: Reader, session: Session) -> Approval:
    route = await approvals_read.get_visible(session, employee, approval_id)
    return await approvals_read.present(session, employee, route)


@router.post("/approvals/{approval_id}/decision", response_model=Approval, operation_id="decideApproval")
async def decide_approval(
    approval_id: uuid.UUID, body: DecisionIn, employee: Decider, session: Session, bus: Bus
) -> Approval:
    async with session.begin():
        route = await approvals.decide(session, bus, employee=employee, route_id=approval_id, body=body)
        return await approvals_read.present(session, employee, route)
