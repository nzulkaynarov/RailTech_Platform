"""Входящие письма и резолюции: `/api/v1/letters…` (eds.yaml, тег `letters`); правила — `services/letters.py`."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bus, get_session, require_permission
from app.models import Employee
from app.schemas.letters import (
    Letter,
    LetterCreate,
    LetterPage,
    LetterRejectIn,
    LetterReturnIn,
    LetterStatus,
    LetterSubmitIn,
    ResolutionIn,
)
from app.schemas.pagination import Cursor, Limit
from app.security.permissions import EdsPermission as P
from app.services import idempotency, letters, letters_read

router = APIRouter(prefix="/api/v1", tags=["letters"])

IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)]
Reader = Annotated[Employee, Depends(require_permission(P.LETTERS_READ))]
Registrar = Annotated[Employee, Depends(require_permission(P.LETTERS_REGISTER))]
Resolver = Annotated[Employee, Depends(require_permission(P.LETTERS_RESOLVE))]
Session = Annotated[AsyncSession, Depends(get_session)]
Bus = Annotated[AsyncBus, Depends(get_bus)]


@router.get("/letters", response_model=LetterPage, operation_id="listLetters")
async def list_letters(
    _: Reader,
    session: Session,
    status: Annotated[list[LetterStatus] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> LetterPage:
    return await letters_read.list_page(session, statuses=status, q=q, cursor=cursor, limit=limit)


@router.post("/letters", response_model=Letter, status_code=201, operation_id="registerLetter")
async def register_letter(
    body: LetterCreate, employee: Registrar, session: Session, bus: Bus, idempotency_key: IdemKey = None
) -> Any:
    async with session.begin():

        async def create() -> Letter:
            letter = await letters.register(session, bus, actor_id=employee.crm_user_id, data=body)
            return await letters_read.present(session, letter)

        return await idempotency.run(
            session,
            crm_user_id=employee.crm_user_id,
            scope="POST /letters",
            key=idempotency_key,
            request_hash=idempotency.body_hash(body),
            status_code=201,
            action=create,
        )


@router.get("/letters/{letter_id}", response_model=Letter, operation_id="getLetter")
async def get_letter(letter_id: uuid.UUID, _: Reader, session: Session) -> Letter:
    return await letters_read.present(session, await letters_read.get_letter(session, letter_id))


@router.post("/letters/{letter_id}/resolution", response_model=Letter, operation_id="resolveLetter")
async def resolve_letter(
    letter_id: uuid.UUID, body: ResolutionIn, employee: Resolver, session: Session, bus: Bus
) -> Letter:
    async with session.begin():
        letter = await letters.resolve(session, bus, actor_id=employee.crm_user_id, letter_id=letter_id, data=body)
        return await letters_read.present(session, letter)


@router.post("/letters/{letter_id}/return", response_model=Letter, operation_id="returnLetter")
async def return_letter(
    letter_id: uuid.UUID, body: LetterReturnIn, employee: Resolver, session: Session, bus: Bus
) -> Letter:
    async with session.begin():
        letter = await letters.return_letter(
            session, bus, actor_id=employee.crm_user_id, letter_id=letter_id, comment=body.comment
        )
        return await letters_read.present(session, letter)


@router.post("/letters/{letter_id}/reject", response_model=Letter, operation_id="rejectLetter")
async def reject_letter(
    letter_id: uuid.UUID, body: LetterRejectIn, employee: Resolver, session: Session, bus: Bus
) -> Letter:
    async with session.begin():
        letter = await letters.reject(
            session, bus, actor_id=employee.crm_user_id, letter_id=letter_id, reason=body.reason
        )
        return await letters_read.present(session, letter)


@router.post("/letters/{letter_id}/submit", response_model=Letter, operation_id="resubmitLetter")
async def resubmit_letter(
    letter_id: uuid.UUID,
    employee: Registrar,
    session: Session,
    body: Annotated[LetterSubmitIn | None, Body()] = None,
) -> Letter:
    async with session.begin():
        letter = await letters.resubmit(session, actor_id=employee.crm_user_id, letter_id=letter_id, data=body)
        return await letters_read.present(session, letter)
