"""Чтение писем: карточка с резолюцией и журналом, страница списка с фильтрами и поиском."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import not_found
from app.models import Acquaintance, Document, Employee, Instruction, InstructionExtension, Letter
from app.schemas.common import ErpLinks, IncomingLetterSender, SenderRef
from app.schemas.letters import (
    AcquaintanceOut,
    Assignee,
    HandedTo,
    InstructionExtensionOut,
    InstructionOut,
    LetterDuplicateRef,
    LetterListItem,
    LetterPage,
    LetterStatus,
    OfficeResolution,
    OutgoingRef,
    RelatedRef,
    Resolution,
    ResolutionDraft,
    ResolutionKind,
)
from app.schemas.letters import Letter as LetterOut
from app.schemas.pagination import decode_cursor
from app.services import dictionaries, files, instructions, journal, paging, reply
from app.services.letters import fmt_pct
from app.services.people import Directory, default_director, load_directory


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def links_of(letter: Letter) -> ErpLinks:
    return ErpLinks(
        erp_request_id=letter.erp_request_id,
        erp_deal_id=letter.erp_deal_id,
        deal_number=letter.deal_number,
        crm_client_id=letter.crm_client_id,
        erp_company_id=letter.erp_company_id,
    )


def sender_of(letter: Letter) -> IncomingLetterSender:
    return IncomingLetterSender(name=letter.sender_name, inn=letter.sender_inn, contact=letter.sender_contact)


def _resolution(letter: Letter, directory: Directory) -> Resolution | None:
    if letter.resolution_kind is not None:  # резолюция делопроизводства — `office_resolution`
        return None
    if letter.resolution_decided_by is None or letter.resolution_due is None or letter.resolution_decided_at is None:
        return None
    return Resolution(
        text=letter.resolution_text or "",
        assignees=[
            Assignee(crm_user_id=a["crm_user_id"], zone=a["zone"], full_name=directory.name(a["crm_user_id"]))
            for a in letter.resolution_assignees or []
        ],
        due=letter.resolution_due,
        min_margin_pct=fmt_pct(letter.resolution_min_margin_pct),
        decided_by=directory.person(letter.resolution_decided_by),
        decided_at=letter.resolution_decided_at,
    )


async def get_letter(session: AsyncSession, letter_id: uuid.UUID) -> Letter:
    letter = (await session.execute(select(Letter).where(Letter.id == letter_id))).scalar_one_or_none()
    if letter is None:
        raise not_found("Письмо не найдено.")
    return letter


async def _related(session: AsyncSession, letter: Letter) -> RelatedRef | None:
    """Связанный документ карточки (P8): предыдущий ВХ или наш ИСХ."""
    if letter.related_letter_id is not None:
        number = (
            await session.execute(select(Letter.number).where(Letter.id == letter.related_letter_id))
        ).scalar_one_or_none()
        if number is not None:
            return RelatedRef(kind="letter_in", id=letter.related_letter_id, number=number)
    if letter.related_document_id is not None:
        number = (
            await session.execute(select(Document.number).where(Document.id == letter.related_document_id))
        ).scalar_one_or_none()
        if number is not None:
            return RelatedRef(kind="letter_out", id=letter.related_document_id, number=number)
    return None


def _draft(letter: Letter, directory: Directory) -> ResolutionDraft | None:
    raw: dict[str, Any] | None = letter.resolution_draft
    if not raw:
        return None
    return ResolutionDraft(
        kind=ResolutionKind(raw["kind"]) if raw.get("kind") else None,
        responsible=directory.person_or_none(raw.get("responsible")),
        due=date.fromisoformat(raw["due"]) if raw.get("due") else None,
        text=raw.get("text"),
        co_executors=[directory.person(uid) for uid in raw.get("co_executors") or []],
        acquaint=[directory.person(uid) for uid in raw.get("acquaint") or []],
        drafted_by=directory.person(int(raw["by"])),
        drafted_at=raw["at"],
    )


def _draft_people(letter: Letter) -> list[int | None]:
    raw: dict[str, Any] = letter.resolution_draft or {}
    return [raw.get("responsible"), raw.get("by"), *(raw.get("co_executors") or []), *(raw.get("acquaint") or [])]


async def _work(
    session: AsyncSession, letter: Letter
) -> tuple[list[Instruction], dict[uuid.UUID, list[InstructionExtension]], list[Acquaintance], dict[uuid.UUID, str]]:
    """Поручения (ответственный первым), их переносы, ознакомление и номера ИСХ-ответов."""
    rows = list(
        (
            await session.execute(
                select(Instruction)
                .where(Instruction.letter_id == letter.id)
                .order_by(Instruction.role.desc(), Instruction.created_at, Instruction.crm_user_id)
            )
        ).scalars()
    )
    extensions: dict[uuid.UUID, list[InstructionExtension]] = {r.id: [] for r in rows}
    if rows:
        found = await session.execute(
            select(InstructionExtension)
            .where(InstructionExtension.instruction_id.in_(list(extensions)))
            .order_by(InstructionExtension.requested_at)
        )
        for ext in found.scalars():
            extensions[ext.instruction_id].append(ext)
    acquaint = list(
        (
            await session.execute(
                select(Acquaintance).where(Acquaintance.letter_id == letter.id).order_by(Acquaintance.created_at)
            )
        ).scalars()
    )
    outgoing_ids = {r.outgoing_document_id for r in rows if r.outgoing_document_id}
    numbers: dict[uuid.UUID, str] = {}
    if outgoing_ids:
        found_numbers = await session.execute(select(Document.id, Document.number).where(Document.id.in_(outgoing_ids)))
        numbers = {doc_id: number for doc_id, number in found_numbers.all() if number}
    return rows, extensions, acquaint, numbers


def _office_resolution(
    letter: Letter, rows: list[Instruction], acquaint: list[Acquaintance], directory: Directory
) -> OfficeResolution | None:
    if letter.resolution_kind is None or letter.resolution_decided_by is None or letter.resolution_decided_at is None:
        return None
    responsible = next((r.crm_user_id for r in rows if r.role == "responsible"), None)
    return OfficeResolution(
        kind=ResolutionKind(letter.resolution_kind),
        text=letter.resolution_text or "",
        due=letter.resolution_due,
        responsible=directory.person_or_none(responsible),
        co_executors=[directory.person(r.crm_user_id) for r in rows if r.role == "co_executor"],
        acquaint=[directory.person(a.crm_user_id) for a in acquaint],
        decided_by=directory.person(letter.resolution_decided_by),
        decided_at=letter.resolution_decided_at,
    )


async def _kind_due_days(session: AsyncSession, letter: Letter) -> int | None:
    """Срок исполнения по умолчанию вида документа (справочник `letter-kinds`, EDS-REG); скрытый вид тоже считается."""
    if letter.doc_kind is None:
        return None
    item = await dictionaries.find(session, dictionaries.LETTER_KINDS, letter.doc_kind, active_only=False)
    days = item.attrs.get("due_days") if item is not None else None
    return days if isinstance(days, int) and not isinstance(days, bool) else None


async def present(session: AsyncSession, letter: Letter, viewer: Employee | None = None) -> LetterOut:
    """Карточка письма: резолюция, поручения, вложения (последние версии), журнал и ответы, видимые `viewer`."""
    rows, extensions, acquaint, numbers = await _work(session, letter)
    ext_people = [p for exts in extensions.values() for e in exts for p in (e.requested_by, e.decided_by)]
    ids = [
        letter.registered_by,
        letter.manager_crm_user_id,
        letter.addressee_crm_user_id,
        letter.resolution_decided_by,
        *(a["crm_user_id"] for a in letter.resolution_assignees or []),
        *(r.crm_user_id for r in rows),
        *(a.crm_user_id for a in acquaint),
        *ext_people,
        *_draft_people(letter),
    ]
    director = None if letter.addressee_crm_user_id else await default_director(session)
    directory = await load_directory(session, [*ids, director])
    entries = await journal.entries(session, "letter", letter.id)
    addressee = letter.addressee_crm_user_id or director
    today = clock.company_date(clock.now())
    return LetterOut(
        id=letter.id,
        number=letter.number,
        status=LetterStatus(letter.status),
        subject=letter.subject,
        summary=letter.summary,
        body_text=letter.body_text,
        sender=sender_of(letter),
        sender_ref=SenderRef(number=letter.sender_ref_number, date=letter.sender_ref_date),
        received_at=letter.received_at,
        registered_at=letter.registered_at,
        registered_by=directory.person_or_none(letter.registered_by),
        addressee=directory.person(addressee) if addressee is not None else directory.person(0),
        manager=directory.person_or_none(letter.manager_crm_user_id),
        urgent=letter.urgent,
        links=links_of(letter),
        files=await files.refs_for(session, letter_id=letter.id),
        resolution=_resolution(letter, directory),
        return_comment=letter.return_comment,
        reject_reason=letter.reject_reason,
        journal=entries,
        kind=letter.doc_kind,
        receipt_method=letter.receipt_method,
        signed_by=letter.signed_by,
        document_due=letter.document_due,
        related=await _related(session, letter),
        track=instructions.track_of(letter),
        on_control=letter.on_control,
        suggested_due=(
            instructions.suggested_due(letter, today, await _kind_due_days(session, letter))
            if letter.status == "awaiting_resolution"
            else None
        ),
        resolution_draft=_draft(letter, directory),
        office_resolution=_office_resolution(letter, rows, acquaint, directory),
        instructions=[
            InstructionOut(
                id=r.id,
                kind=ResolutionKind(r.kind),
                role=r.role,
                person=directory.person(r.crm_user_id),
                due=r.due,
                text=r.text,
                status=r.status,
                overdue=r.status == instructions.IN_WORK and r.due < today,
                report=r.report,
                files=await files.refs_for(session, instruction_id=r.id),
                outgoing=OutgoingRef(id=r.outgoing_document_id, number=numbers[r.outgoing_document_id])
                if r.outgoing_document_id in numbers
                else None,
                handed_to=HandedTo.model_validate(r.handed_to) if r.handed_to else None,
                executed_at=r.executed_at,
                extensions=[
                    InstructionExtensionOut(
                        id=e.id,
                        old_due=e.old_due,
                        new_due=e.new_due,
                        reason=e.reason,
                        status=e.status,
                        requested_by=directory.person(e.requested_by),
                        requested_at=e.requested_at,
                        decided_by=directory.person_or_none(e.decided_by),
                        decided_at=e.decided_at,
                        comment=e.comment,
                    )
                    for e in extensions[r.id]
                ],
            )
            for r in rows
        ],
        acquaintances=[
            AcquaintanceOut(person=directory.person(a.crm_user_id), acknowledged_at=a.acknowledged_at) for a in acquaint
        ],
        executed_at=letter.executed_at,
        close_reason=letter.close_reason,
        close_comment=letter.close_comment,
        duplicate_of=await _duplicate_of(session, letter),
        replies=await reply.replies_for(session, viewer, letter),
    )


async def _duplicate_of(session: AsyncSession, letter: Letter) -> LetterDuplicateRef | None:
    """Оригинал письма-дубля (EDS-DUP)."""
    if letter.duplicate_of_id is None:
        return None
    number = (await session.execute(select(Letter.number).where(Letter.id == letter.duplicate_of_id))).scalar_one()
    return LetterDuplicateRef(id=letter.duplicate_of_id, number=number)


async def list_page(
    session: AsyncSession,
    *,
    statuses: list[LetterStatus] | None,
    q: str | None,
    cursor: str | None,
    limit: int,
    on_control: bool | None = None,
    overdue: bool | None = None,
    kind: str | None = None,
) -> LetterPage:
    today = clock.company_date(clock.now())
    stmt = select(Letter)
    if kind is not None:
        stmt = stmt.where(Letter.doc_kind == kind)
    if statuses:
        stmt = stmt.where(Letter.status.in_([s.value for s in statuses]))
    if on_control is not None:
        stmt = stmt.where(Letter.on_control.is_(on_control))
    if overdue is not None:
        clause = instructions.overdue_clause(today)
        stmt = stmt.where(clause if overdue else ~clause)
    if q and q.strip():
        like = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(
                Letter.number.ilike(like, escape="\\"),
                Letter.subject.ilike(like, escape="\\"),
                Letter.sender_name.ilike(like, escape="\\"),
                Letter.deal_number.ilike(like, escape="\\"),
                cast(Letter.erp_request_id, String).ilike(like, escape="\\"),
            )
        )
    stmt = paging.apply(stmt, Letter.registered_at, Letter.id, decode_cursor(cursor), limit)
    rows = list((await session.execute(stmt)).scalars().all())
    page, next_cursor = paging.cut(rows, limit, lambda r: r.registered_at, lambda r: r.id)
    executors: dict[uuid.UUID, int] = {}
    late: set[uuid.UUID] = set()
    if page:
        work = await session.execute(
            select(
                Instruction.letter_id, Instruction.crm_user_id, Instruction.role, Instruction.status, Instruction.due
            ).where(Instruction.letter_id.in_([r.id for r in page]))
        )
        for letter_id, uid, role, status, due in work.all():
            if role == "responsible":
                executors[letter_id] = uid
            if status == instructions.IN_WORK and due < today:
                late.add(letter_id)
    directory = await load_directory(session, executors.values())
    items = [
        LetterListItem(
            id=r.id,
            number=r.number,
            subject=r.subject,
            sender=sender_of(r),
            received_at=r.received_at,
            status=LetterStatus(r.status),
            links=links_of(r),
            urgent=r.urgent,
            due=r.resolution_due,
            kind=r.doc_kind,
            track=instructions.track_of(r),
            on_control=r.on_control,
            overdue=r.id in late,
            executor=directory.person(executors[r.id]) if r.id in executors else None,
        )
        for r in page
    ]
    return LetterPage(items=items, next_cursor=next_cursor)
