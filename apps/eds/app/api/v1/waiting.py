"""«Вы ждёте других»: `/api/v1/waiting` и `…/remind` (eds.yaml, тег `waiting`)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bus, get_session, require_permission
from app.models import Employee
from app.schemas.waiting import RemindOut, WaitingKind, WaitingList
from app.services import waiting

router = APIRouter(prefix="/api/v1", tags=["waiting"])

# Любой активный сотрудник: сужение — в сервисе («мои» объекты: автор документа, автор резолюции).
Anyone = Annotated[Employee, Depends(require_permission())]
Session = Annotated[AsyncSession, Depends(get_session)]
Bus = Annotated[AsyncBus, Depends(get_bus)]


@router.get("/waiting", response_model=WaitingList, operation_id="listWaitingOnOthers")
async def list_waiting(employee: Anyone, session: Session) -> WaitingList:
    return await waiting.list_waiting(session, employee)


@router.post("/waiting/{kind}/{object_id}/remind", response_model=RemindOut, operation_id="remindWaitingOnOthers")
async def remind(kind: WaitingKind, object_id: uuid.UUID, employee: Anyone, session: Session, bus: Bus) -> RemindOut:
    async with session.begin():
        return await waiting.remind(session, bus, employee, kind, object_id)
