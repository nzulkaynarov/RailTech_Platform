"""Входящие письма и резолюции: `/api/v1/letters…` (eds.yaml, тег `letters`); правила — `services/letters.py`."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Response
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bus, get_session, require_permission
from app.models import Employee
from app.schemas.letters import (
    EmployeeList,
    ExtensionDecisionIn,
    ExtensionRequestIn,
    InstructionCompleteIn,
    Letter,
    LetterCreate,
    LetterDuplicateCheck,
    LetterDuplicateCheckIn,
    LetterDuplicateList,
    LetterKindItem,
    LetterKindList,
    LetterMarkDuplicateIn,
    LetterPage,
    LetterRejectIn,
    LetterReturnIn,
    LetterStatus,
    LetterSubmitIn,
    LetterTasks,
    OfficeResolutionIn,
    ResolutionDraftIn,
    ResolutionIn,
)
from app.schemas.pagination import Cursor, Limit
from app.security.permissions import EdsPermission as P
from app.services import dictionaries, idempotency, instructions, letter_dedup, letters, letters_read

router = APIRouter(prefix="/api/v1", tags=["letters"])

IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)]
Reader = Annotated[Employee, Depends(require_permission(P.LETTERS_READ))]
Registrar = Annotated[Employee, Depends(require_permission(P.LETTERS_REGISTER))]
Resolver = Annotated[Employee, Depends(require_permission(P.LETTERS_RESOLVE))]
# Справочник видов и проверка дубля — тем, кто читает или регистрирует письма (P8).
Clerk = Annotated[Employee, Depends(require_permission(P.LETTERS_READ, P.LETTERS_REGISTER))]
# Проект резолюции и выбор сотрудников — делопроизводителю и директору (P8b).
Drafter = Annotated[Employee, Depends(require_permission(P.LETTERS_REGISTER, P.LETTERS_RESOLVE))]
# Любой активный сотрудник; сужение — в сервисе (исполнитель, «ознакомить», автор резолюции; P8b).
Anyone = Annotated[Employee, Depends(require_permission())]
Session = Annotated[AsyncSession, Depends(get_session)]
Bus = Annotated[AsyncBus, Depends(get_bus)]


@router.get("/letter-kinds", response_model=LetterKindList, operation_id="listLetterKinds")
async def list_letter_kinds(_: Clerk, session: Session) -> LetterKindList:
    """Действующие виды документа — справочник `letter-kinds` (EDS-REG); весь — `/dictionaries/letter-kinds`."""
    found = await dictionaries.list_items(session, dictionaries.LETTER_KINDS)
    return LetterKindList(
        items=[
            LetterKindItem(
                code=item.code,
                name=item.name.model_dump(),
                urgent=bool(item.attrs.get("urgent")),
                due_days=item.attrs.get("due_days") if isinstance(item.attrs.get("due_days"), int) else None,
            )
            for item in found.items
        ]
    )


@router.get(
    "/letter-duplicates",
    response_model=LetterDuplicateList,
    response_model_exclude_none=True,
    operation_id="findLetterDuplicates",
)
async def find_letter_duplicates(
    _: Clerk,
    session: Session,
    ref_number: Annotated[str, Query(min_length=1, max_length=64)],
    sender_name: Annotated[str | None, Query(max_length=255)] = None,
    crm_client_id: Annotated[int | None, Query()] = None,
) -> LetterDuplicateList:
    return await letters.find_duplicates(
        session, sender_name=sender_name, crm_client_id=crm_client_id, ref_number=ref_number
    )


@router.post("/letters/duplicates-check", response_model=LetterDuplicateCheck, operation_id="checkLetterDuplicates")
async def check_letter_duplicates(
    body: LetterDuplicateCheckIn, employee: Clerk, session: Session
) -> LetterDuplicateCheck:
    """EDS-DUP: то же письмо (`exact`) и похожие — до регистрации; ничего не меняет."""
    return await letter_dedup.check(session, letter_dedup.Probe.of(body), actor_id=employee.crm_user_id)


@router.get("/letters", response_model=LetterPage, operation_id="listLetters")
async def list_letters(
    _: Reader,
    session: Session,
    status: Annotated[list[LetterStatus] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    on_control: Annotated[bool | None, Query()] = None,
    overdue: Annotated[bool | None, Query()] = None,
    kind: Annotated[str | None, Query(pattern=r"^[a-z][a-z_]{0,31}$")] = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> LetterPage:
    return await letters_read.list_page(
        session,
        statuses=status,
        q=q,
        cursor=cursor,
        limit=limit,
        on_control=on_control,
        overdue=overdue,
        kind=kind,
    )


@router.post("/letters", response_model=Letter, status_code=201, operation_id="registerLetter")
async def register_letter(
    body: LetterCreate,
    employee: Registrar,
    session: Session,
    bus: Bus,
    response: Response,
    idempotency_key: IdemKey = None,
) -> Any:
    created = True
    async with session.begin():

        async def create() -> Letter:
            nonlocal created
            letter, created = await letters.register_once(session, bus, actor_id=employee.crm_user_id, data=body)
            return await letters_read.present(session, letter)

        result = await idempotency.run(
            session,
            crm_user_id=employee.crm_user_id,
            scope="POST /letters",
            key=idempotency_key,
            request_hash=idempotency.body_hash(body),
            status_code=201,
            action=create,
        )
    if not created:  # письмо общего ящика уже имеет ВХ (W18A-P2-3): тот же ВХ, 200 вместо 201
        response.status_code = 200
    return result


@router.get("/letters/{letter_id}", response_model=Letter, operation_id="getLetter")
async def get_letter(letter_id: uuid.UUID, employee: Anyone, session: Session) -> Letter:
    letter = await letters_read.get_letter(session, letter_id)
    await instructions.require_readable(session, employee, letter)
    return await letters_read.present(session, letter)


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


@router.post("/letters/{letter_id}/duplicate", response_model=Letter, operation_id="markLetterDuplicate")
async def mark_letter_duplicate(
    letter_id: uuid.UUID, body: LetterMarkDuplicateIn, employee: Registrar, session: Session
) -> Letter:
    """«Это дубль ВХ-…» (EDS-DUP): письмо закрыто, ссылка на оригинал, поручения отменены."""
    async with session.begin():
        letter = await letter_dedup.mark_duplicate(
            session, actor_id=employee.crm_user_id, letter_id=letter_id, data=body
        )
        return await letters_read.present(session, letter)


# --- путь делопроизводства (P8b, SPEC-v3 §3.2a) -------------------------------------------------------------------


@router.put("/letters/{letter_id}/resolution-draft", response_model=Letter, operation_id="saveResolutionDraft")
async def save_resolution_draft(
    letter_id: uuid.UUID, body: ResolutionDraftIn, employee: Drafter, session: Session
) -> Letter:
    async with session.begin():
        letter = await instructions.save_draft(session, actor_id=employee.crm_user_id, letter_id=letter_id, data=body)
        return await letters_read.present(session, letter)


@router.post("/letters/{letter_id}/office-resolution", response_model=Letter, operation_id="resolveOfficeLetter")
async def resolve_office_letter(
    letter_id: uuid.UUID, body: OfficeResolutionIn, employee: Resolver, session: Session, bus: Bus
) -> Letter:
    async with session.begin():
        letter = await instructions.resolve_office(
            session, bus, actor_id=employee.crm_user_id, letter_id=letter_id, data=body
        )
        return await letters_read.present(session, letter)


@router.post("/letters/{letter_id}/acquaint", response_model=Letter, operation_id="acknowledgeLetter")
async def acknowledge_letter(letter_id: uuid.UUID, employee: Anyone, session: Session) -> Letter:
    async with session.begin():
        letter = await instructions.acknowledge(session, actor_id=employee.crm_user_id, letter_id=letter_id)
        return await letters_read.present(session, letter)


@router.post("/instructions/{instruction_id}/complete", response_model=Letter, operation_id="completeInstruction")
async def complete_instruction(
    instruction_id: uuid.UUID, body: InstructionCompleteIn, employee: Anyone, session: Session, bus: Bus
) -> Letter:
    async with session.begin():
        letter = await instructions.complete(
            session, bus, actor_id=employee.crm_user_id, instruction_id=instruction_id, data=body
        )
        return await letters_read.present(session, letter)


@router.post(
    "/instructions/{instruction_id}/extension", response_model=Letter, operation_id="requestInstructionExtension"
)
async def request_instruction_extension(
    instruction_id: uuid.UUID, body: ExtensionRequestIn, employee: Anyone, session: Session, bus: Bus
) -> Letter:
    async with session.begin():
        letter = await instructions.request_extension(
            session, bus, actor_id=employee.crm_user_id, instruction_id=instruction_id, data=body
        )
        return await letters_read.present(session, letter)


@router.post(
    "/instructions/{instruction_id}/extension/decision",
    response_model=Letter,
    operation_id="decideInstructionExtension",
)
async def decide_instruction_extension(
    instruction_id: uuid.UUID, body: ExtensionDecisionIn, employee: Anyone, session: Session, bus: Bus
) -> Letter:
    async with session.begin():
        letter = await instructions.decide_extension(
            session, bus, actor_id=employee.crm_user_id, instruction_id=instruction_id, data=body
        )
        return await letters_read.present(session, letter)


@router.get("/letter-tasks", response_model=LetterTasks, operation_id="listMyLetterTasks")
async def list_my_letter_tasks(employee: Anyone, session: Session) -> LetterTasks:
    return await instructions.my_tasks(session, crm_user_id=employee.crm_user_id)


# Администратору (`bus.manage`) — для людей общих шаблонов резолюций (EDS-REG).
StaffReader = Annotated[Employee, Depends(require_permission(P.LETTERS_REGISTER, P.LETTERS_RESOLVE, P.BUS_MANAGE))]


@router.get("/employees", response_model=EmployeeList, operation_id="listActiveEmployees")
async def list_active_employees(_: StaffReader, session: Session) -> EmployeeList:
    return await instructions.active_employees(session)
