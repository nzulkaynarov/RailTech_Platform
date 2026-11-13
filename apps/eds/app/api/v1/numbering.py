"""Обозначения номеров реестра (`/api/v1/numbering-labels`, eds.yaml; задача «Н», решение владельца 2026-11-13):
читает любой сотрудник (образец в настройках), меняет администратор. Правила — `services/numbering.py`."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_permission
from app.models import Employee
from app.schemas.numbering import NumberLabelItem, NumberLabels, NumberLabelsIn
from app.security.permissions import EdsPermission as P
from app.services import numbering

router = APIRouter(prefix="/api/v1/numbering-labels", tags=["registry"])

Reader = Annotated[Employee, Depends(require_permission())]
Admin = Annotated[Employee, Depends(require_permission(P.BUS_MANAGE))]
Session = Annotated[AsyncSession, Depends(get_session)]


def _present(current: dict[numbering.NumberKind, str]) -> NumberLabels:
    rows = numbering.examples(current, datetime.now(UTC))
    return NumberLabels(items=[NumberLabelItem(kind=k, label=label, example=ex) for k, label, ex in rows])


@router.get("", response_model=NumberLabels, operation_id="getNumberLabels")
async def get_number_labels(employee: Reader, session: Session) -> NumberLabels:
    return _present(await numbering.labels(session))


@router.put("", response_model=NumberLabels, operation_id="setNumberLabels")
async def set_number_labels(body: NumberLabelsIn, employee: Admin, session: Session) -> NumberLabels:
    async with session.begin():
        return _present(await numbering.set_labels(session, body.labels))
