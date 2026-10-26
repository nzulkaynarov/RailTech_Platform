"""Чтение документов: карточка с решениями и журналом, страница списка с видимостью «автор или участник»."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import not_found
from app.models import ApprovalRoute, ApprovalStep, Document, Employee
from app.schemas.approvals import Decision
from app.schemas.common import LetterSender, Money
from app.schemas.documents import Document as DocumentOut
from app.schemas.documents import (
    DocumentDecision,
    DocumentKind,
    DocumentListItem,
    DocumentPage,
    DocumentStatus,
)
from app.schemas.pagination import decode_cursor
from app.services import access, files, journal, paging
from app.services.people import Directory, load_directory

_DECISION = {"approved": Decision.APPROVE, "returned": Decision.RETURN, "rejected": Decision.REJECT}


def money_of(document: Document) -> Money | None:
    if document.amount is None or document.currency is None:
        return None
    return Money(amount=f"{document.amount:.2f}", currency=document.currency)


async def get_visible(session: AsyncSession, employee: Employee, document_id: uuid.UUID) -> Document:
    """Документ, если сотрудник автор, участник маршрута или у него `registry.read`; иначе 404."""
    stmt = select(Document).where(Document.id == document_id, access.document_visible(employee))
    document = (await session.execute(stmt)).scalar_one_or_none()
    if document is None:
        raise not_found("Документ не найден.")
    return document


async def _decisions(session: AsyncSession, document_id: uuid.UUID, directory: Directory) -> list[DocumentDecision]:
    rows = await session.execute(
        select(ApprovalRoute.round, ApprovalStep)
        .join(ApprovalStep, ApprovalStep.approval_id == ApprovalRoute.id)
        .where(ApprovalRoute.document_id == document_id, ApprovalStep.decided_at.is_not(None))
        .order_by(ApprovalStep.decided_at)
    )
    return [
        DocumentDecision(
            round=round_no,
            step=step.index,
            decision=_DECISION[step.status],
            comment=step.comment,
            by=directory.person(step.decided_by or 0),
            at=step.decided_at,
        )
        for round_no, step in rows.all()
    ]


async def present(session: AsyncSession, document: Document) -> DocumentOut:
    route_id = (
        await session.execute(
            select(ApprovalRoute.id)
            .where(ApprovalRoute.document_id == document.id)
            .order_by(ApprovalRoute.round.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    routes = (
        await session.execute(
            select(ApprovalStep.decided_by).join(ApprovalRoute).where(ApprovalRoute.document_id == document.id)
        )
    ).scalars()
    directory = await load_directory(session, [document.author_crm_user_id, document.addressee_crm_user_id, *routes])
    decisions = await _decisions(session, document.id, directory)
    entries = await journal.entries(session, "document", document.id)
    recipient = (
        LetterSender(name=document.recipient_name, inn=document.recipient_inn)
        if document.kind == DocumentKind.LETTER_OUT.value
        else None
    )
    return DocumentOut(
        id=document.id,
        kind=DocumentKind(document.kind),
        number=document.number,
        status=DocumentStatus(document.status),
        version=document.version,
        subject=document.subject,
        text=document.text,
        author=directory.person(document.author_crm_user_id),
        addressee=directory.person_or_none(document.addressee_crm_user_id),
        amount=money_of(document),
        due_date=document.due_date,
        files=await files.refs_for(session, document_id=document.id),
        source_message_id=document.source_message_id,
        erp_deal_id=document.erp_deal_id,
        deal_number=document.deal_number,
        recipient=recipient,
        in_reply_to=document.in_reply_to,
        approval_id=route_id,
        decisions=decisions,
        journal=entries,
        created_at=document.created_at,
        updated_at=document.updated_at,
        archived_at=document.archived_at,
    )


async def list_page(
    session: AsyncSession,
    employee: Employee,
    *,
    kinds: list[DocumentKind] | None,
    statuses: list[DocumentStatus] | None,
    mine: bool,
    cursor: str | None,
    limit: int,
) -> DocumentPage:
    stmt = select(Document).where(access.document_visible(employee))
    if kinds:
        stmt = stmt.where(Document.kind.in_([k.value for k in kinds]))
    if statuses:
        stmt = stmt.where(Document.status.in_([s.value for s in statuses]))
    if mine:
        stmt = stmt.where(Document.author_crm_user_id == employee.crm_user_id)
    stmt = paging.apply(stmt, Document.created_at, Document.id, decode_cursor(cursor), limit)
    rows = list((await session.execute(stmt)).scalars().all())
    page, next_cursor = paging.cut(rows, limit, lambda r: r.created_at, lambda r: r.id)
    directory = await load_directory(session, (r.author_crm_user_id for r in page))
    items = [
        DocumentListItem(
            id=r.id,
            kind=DocumentKind(r.kind),
            number=r.number,
            status=DocumentStatus(r.status),
            subject=r.subject,
            author=directory.person(r.author_crm_user_id),
            amount=money_of(r),
            due_date=r.due_date,
            created_at=r.created_at,
        )
        for r in page
    ]
    return DocumentPage(items=items, next_cursor=next_cursor)
