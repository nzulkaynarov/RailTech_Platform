"""Чтение писем: карточка с резолюцией и журналом, страница списка с фильтрами и поиском."""

import uuid

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import not_found
from app.models import Letter
from app.schemas.common import ErpLinks, IncomingLetterSender, SenderRef
from app.schemas.letters import (
    Assignee,
    LetterListItem,
    LetterPage,
    LetterStatus,
    Resolution,
)
from app.schemas.letters import Letter as LetterOut
from app.schemas.pagination import decode_cursor
from app.services import files, journal, paging
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


async def present(session: AsyncSession, letter: Letter) -> LetterOut:
    """Карточка письма: резолюция, вложения (последние версии) и журнал."""
    ids = [
        letter.registered_by,
        letter.manager_crm_user_id,
        letter.addressee_crm_user_id,
        letter.resolution_decided_by,
        *(a["crm_user_id"] for a in letter.resolution_assignees or []),
    ]
    director = None if letter.addressee_crm_user_id else await default_director(session)
    directory = await load_directory(session, [*ids, director])
    entries = await journal.entries(session, "letter", letter.id)
    addressee = letter.addressee_crm_user_id or director
    return LetterOut(
        id=letter.id,
        number=letter.number,
        status=LetterStatus(letter.status),
        subject=letter.subject,
        summary=letter.summary,
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
    )


async def list_page(
    session: AsyncSession, *, statuses: list[LetterStatus] | None, q: str | None, cursor: str | None, limit: int
) -> LetterPage:
    stmt = select(Letter)
    if statuses:
        stmt = stmt.where(Letter.status.in_([s.value for s in statuses]))
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
        )
        for r in page
    ]
    return LetterPage(items=items, next_cursor=next_cursor)
