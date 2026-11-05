"""Чтение документов: карточка с решениями и журналом, страница списка с видимостью «автор или участник»."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import not_found
from app.models import ApprovalRoute, ApprovalStep, Document, DocumentPayment, DocumentRender, Employee, StoredFile
from app.schemas.approvals import Decision
from app.schemas.common import LetterSender, Money
from app.schemas.documents import Document as DocumentOut
from app.schemas.documents import (
    DocumentDecision,
    DocumentKind,
    DocumentListItem,
    DocumentMailing,
    DocumentPage,
    DocumentStatus,
    OutgoingLetter,
    RegistrationRequest,
)
from app.schemas.documents import DocumentPayment as PaymentOut
from app.schemas.pagination import decode_cursor
from app.services import access, files, journal, letter_mail, paging, renders, reply
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


async def payment_of(session: AsyncSession, document: Document) -> PaymentOut | None:
    """Факт оплаты служебной записки, если бухгалтер её оплатил."""
    paid = await session.get(DocumentPayment, document.id)
    if paid is None:
        return None
    directory = await load_directory(session, [paid.paid_by_crm_user_id])
    return PaymentOut(
        paid_on=paid.paid_on,
        amount=Money(amount=f"{paid.amount:.2f}", currency=paid.currency),
        receipt_file_id=paid.receipt_file_id,
        note=paid.note,
        paid_by=directory.person(paid.paid_by_crm_user_id),
        recorded_at=paid.created_at,
    )


async def letter_of(session: AsyncSession, document: Document) -> OutgoingLetter | None:
    """Письмо на бланке (P4): тело и реквизиты, последний PDF, журнал отправки, передача на регистрацию."""
    if document.kind != DocumentKind.LETTER_OUT.value:
        return None
    mailings = await letter_mail.for_document(session, document.id)
    directory = await load_directory(session, [document.registration_requested_by, *(m.requested_by for m in mailings)])
    render = await session.get(DocumentRender, document.pdf_hash) if document.pdf_hash else None
    requested = (
        RegistrationRequest(
            by=directory.person(document.registration_requested_by), at=document.registration_requested_at
        )
        if document.registration_requested_by is not None and document.registration_requested_at is not None
        else None
    )
    return OutgoingLetter(
        body=document.body,
        recipient_attention=document.recipient_attention,
        recipient_email=document.recipient_email,
        signatory_name=document.signatory_name,
        signatory_position=document.signatory_position,
        pdf=renders.present(render) if render and not renders.is_unmarked_draft(render) else None,
        mailings=[
            DocumentMailing(
                id=m.id,
                to=list(m.recipients),
                status=m.status,
                reason=m.reason,
                requested_by=directory.person_or_none(m.requested_by),
                requested_at=m.requested_at,
                finished_at=m.finished_at,
            )
            for m in mailings
        ],
        registration_requested=requested,
    )


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
    directory = await load_directory(
        session,
        [
            document.author_crm_user_id,
            document.addressee_crm_user_id,
            document.signed_by_crm_user_id,
            document.acting_for_crm_user_id,
            *routes,
        ],
    )
    decisions = await _decisions(session, document.id, directory)
    entries = await journal.entries(session, "document", document.id)
    recipient = (
        LetterSender(name=document.recipient_name, inn=document.recipient_inn)
        if document.kind == DocumentKind.LETTER_OUT.value
        else None
    )
    verification_url = (
        f"https://{get_settings().cabinet_domain}/v/{document.verification_code}"
        if document.verification_code
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
        reply_to=await reply.reply_to_ref(session, document.in_reply_to),
        letter=await letter_of(session, document),
        approval_id=route_id,
        payment=await payment_of(session, document),
        decisions=decisions,
        journal=entries,
        created_at=document.created_at,
        updated_at=document.updated_at,
        archived_at=document.archived_at,
        signed_at=document.signed_at,
        signed_by=directory.person_or_none(document.signed_by_crm_user_id),
        signing_authority_id=document.signing_authority_id,
        signatory_basis=document.signatory_basis,
        signatory_basis_text=document.signatory_basis_text,
        acting_for=directory.person_or_none(document.acting_for_crm_user_id),
        verification_code=document.verification_code,
        verification_url=verification_url,
        dispatch_method=document.dispatch_method,
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
    ids = [r.id for r in page]
    count_rows = await session.execute(
        select(StoredFile.document_id, func.count())
        .where(StoredFile.document_id.in_(ids))
        .group_by(StoredFile.document_id)
    )
    counts = dict(count_rows.all())
    paid_rows = await session.execute(
        select(DocumentPayment.document_id, DocumentPayment.paid_on).where(DocumentPayment.document_id.in_(ids))
    )
    paid_on = dict(paid_rows.all())
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
            files_count=counts.get(r.id, 0),
            paid_on=paid_on.get(r.id),
            created_at=r.created_at,
        )
        for r in page
    ]
    return DocumentPage(items=items, next_cursor=next_cursor)
