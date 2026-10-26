"""Документы EDS: служебная записка, заявление, отчёт, исходящее письмо (SPEC-v3 §3.2; eds.yaml, тег `documents`).

`memo`/`application`/`report`: номер (`СЗ|ЗЯ|ОТ-ГГГГ/NNN`) — при создании, `document.registered`; отправка открывает
круг маршрута (`approval.requested`), после возврата версия растёт. `letter_out`: номер `ИСХ-NNN/ГГ` — при отправке,
затем архив.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.errors import conflict, forbidden, forbidden_reason, invalid_fields, not_found
from app.models import ApprovalRoute, Document, DocumentVersion, Employee, Letter
from app.schemas.approvals import ApprovalTemplate
from app.schemas.common import Money
from app.schemas.documents import DocumentCreate, DocumentKind, DocumentStatus, DocumentSubmitIn
from app.security.permissions import EdsPermission as P
from app.services import access, approvals, document_state, events, files, journal, numbering
from app.services.people import holds_permission, load_directory

_NUMBER_KIND = {
    DocumentKind.MEMO: numbering.NumberKind.MEMO,
    DocumentKind.APPLICATION: numbering.NumberKind.APPLICATION,
    DocumentKind.REPORT: numbering.NumberKind.REPORT,
    DocumentKind.LETTER_OUT: numbering.NumberKind.OUTGOING,
}
_TEMPLATE = {
    DocumentKind.MEMO: ApprovalTemplate.MEMO,
    DocumentKind.APPLICATION: ApprovalTemplate.APPLICATION,
    DocumentKind.REPORT: ApprovalTemplate.REPORT,
}


def required_permission(kind: DocumentKind) -> P:
    """`letter_out` создаёт и отправляет регистратор писем, остальное — любой с `memos.create`."""
    return P.LETTERS_REGISTER if kind is DocumentKind.LETTER_OUT else P.MEMOS_CREATE


def require_kind_permission(employee: Employee, kind: DocumentKind) -> None:
    needed = required_permission(kind)
    if not access.has(employee, needed):
        raise forbidden((needed.value,))


def _check_amount(amount: Money | None) -> None:
    if amount is not None and Decimal(amount.amount) <= 0:
        raise invalid_fields("Сумма должна быть больше нуля.", amount="must_be_positive")


async def _check_addressee(session: AsyncSession, kind: DocumentKind, addressee: int | None) -> None:
    """Конкретный адресат решает первый шаг, поэтому обязан быть активным сотрудником с `memos.approve`."""
    if addressee is None or kind is DocumentKind.LETTER_OUT:
        return
    if not await holds_permission(session, addressee, P.MEMOS_APPROVE.value):
        raise invalid_fields("Адресат не может согласовывать документы.", addressee_crm_user_id="cannot_approve")


async def deal_number_for(session: AsyncSession, erp_deal_id: int | None) -> str | None:
    """Бизнес-номер сделки ERP по ссылкам, уже известным EDS (письмо или КП по этой сделке)."""
    if erp_deal_id is None:
        return None
    letter = await session.execute(
        select(Letter.deal_number)
        .where(Letter.erp_deal_id == erp_deal_id, Letter.deal_number.is_not(None))
        .order_by(Letter.registered_at.desc())
        .limit(1)
    )
    found = letter.scalar_one_or_none()
    if found is not None:
        return found
    route = await session.execute(
        select(ApprovalRoute.deal_number)
        .where(ApprovalRoute.erp_deal_id == erp_deal_id, ApprovalRoute.deal_number.is_not(None))
        .limit(1)
    )
    return route.scalar_one_or_none()


async def get_for_update(session: AsyncSession, document_id: uuid.UUID) -> Document:
    stmt = select(Document).where(Document.id == document_id).with_for_update()
    document = (await session.execute(stmt)).scalar_one_or_none()
    if document is None:
        raise not_found("Документ не найден.")
    return document


async def _publish_registered(
    session: AsyncSession, bus: AsyncBus, document: Document, *, registered_at: datetime, actor_id: int
) -> None:
    ids = [document.author_crm_user_id, document.addressee_crm_user_id]
    directory = await load_directory(session, ids)
    body: dict[str, Any] = {
        "eds_document_id": str(document.id),
        "kind": document.kind,
        "number": document.number,
        "subject": document.subject,
        "author": directory.person(document.author_crm_user_id).model_dump(),
        "registered_at": registered_at.isoformat(),
        "amount": None
        if document.amount is None
        else {"amount": f"{document.amount:.2f}", "currency": document.currency},
        "due_date": document.due_date.isoformat() if document.due_date else None,
        "erp_deal_id": document.erp_deal_id,
        "deal_number": document.deal_number,
    }
    if document.addressee_crm_user_id is not None:
        body["addressee"] = directory.person(document.addressee_crm_user_id).model_dump()
    await events.publish(
        bus,
        session,
        "document.registered",
        {"document": body, "actor": events.actor(actor_id)},
        subject=str(document.number),
    )


async def create(session: AsyncSession, bus: AsyncBus, *, employee: Employee, data: DocumentCreate) -> Document:
    """Черновик документа. `memo`/`application`/`report` получают номер сразу, `letter_out` — при отправке."""
    require_kind_permission(employee, data.kind)
    is_letter = data.kind is DocumentKind.LETTER_OUT
    if not is_letter and (data.recipient is not None or data.in_reply_to is not None):
        raise invalid_fields("Адресат и ответ на письмо — только у исходящего письма.", recipient="letter_out_only")
    _check_amount(data.amount)
    await _check_addressee(session, data.kind, data.addressee_crm_user_id)
    if data.in_reply_to is not None and await session.get(Letter, data.in_reply_to) is None:
        raise invalid_fields("Входящее письмо не найдено.", in_reply_to="not_found")
    now = clock.now()
    document = Document(
        id=uuid.uuid4(),
        kind=data.kind.value,
        status=DocumentStatus.DRAFT.value,
        subject=data.subject,
        text=data.text,
        author_crm_user_id=employee.crm_user_id,
        addressee_crm_user_id=data.addressee_crm_user_id,
        amount=Decimal(data.amount.amount) if data.amount else None,
        currency=data.amount.currency if data.amount else None,
        due_date=data.due_date,
        source_message_id=data.source_message_id,
        erp_deal_id=data.erp_deal_id,
        deal_number=await deal_number_for(session, data.erp_deal_id),
        recipient_name=data.recipient.name if data.recipient else None,
        recipient_inn=data.recipient.inn if data.recipient else None,
        in_reply_to=data.in_reply_to,
        created_at=now,
        updated_at=now,
    )
    if not is_letter:
        document.number = await numbering.allocate(session, _NUMBER_KIND[data.kind], now)
    session.add(document)
    await session.flush()
    await journal.record(session, "document.created", by=employee.crm_user_id, document_id=document.id)
    await files.attach(session, data.file_ids, actor_id=employee.crm_user_id, document_id=document.id)
    if not is_letter:
        await _publish_registered(session, bus, document, registered_at=now, actor_id=employee.crm_user_id)
    return document


def _apply_edits(document: Document, edits: DocumentSubmitIn) -> None:
    if edits.subject is not None:
        document.subject = edits.subject
    if edits.text is not None:
        document.text = edits.text
    if "amount" in edits.model_fields_set:
        document.amount = Decimal(edits.amount.amount) if edits.amount else None
        document.currency = edits.amount.currency if edits.amount else None
    if "due_date" in edits.model_fields_set:
        document.due_date = edits.due_date


async def _snapshot(session: AsyncSession, document: Document, employee: Employee) -> None:
    body = {
        "subject": document.subject,
        "text": document.text,
        "amount": None
        if document.amount is None
        else {"amount": f"{document.amount:.2f}", "currency": document.currency},
        "due_date": document.due_date.isoformat() if document.due_date else None,
    }
    session.add(
        DocumentVersion(
            document_id=document.id,
            version=document.version,
            body=body,
            created_by=employee.crm_user_id,
            created_at=clock.now(),
        )
    )
    await session.flush()


async def submit(
    session: AsyncSession, bus: AsyncBus, *, employee: Employee, document_id: uuid.UUID, edits: DocumentSubmitIn | None
) -> Document:
    """Отправить на согласование (или отправить исходящее письмо). Только автор; другой статус — 409 `invalid_state`."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    kind = DocumentKind(document.kind)
    require_kind_permission(employee, kind)
    if document.author_crm_user_id != employee.crm_user_id:
        raise forbidden_reason("not_author", "Отправить документ может только его автор.")
    allowed = {DocumentStatus.DRAFT.value} if kind is DocumentKind.LETTER_OUT else {"draft", "returned"}
    if document.status not in allowed:
        raise conflict("invalid_state", "Документ нельзя отправить в текущем статусе.", status=document.status)
    changes = edits or DocumentSubmitIn()
    _check_amount(changes.amount)
    _apply_edits(document, changes)
    if changes.file_ids:
        await files.attach(session, changes.file_ids, actor_id=employee.crm_user_id, document_id=document.id)
    if kind is DocumentKind.LETTER_OUT:
        await _send_letter(session, bus, document, employee)
    else:
        await _open_approval(session, bus, document, employee, kind)
    return document


async def _send_letter(session: AsyncSession, bus: AsyncBus, document: Document, employee: Employee) -> None:
    now = clock.now()
    document.number = await numbering.allocate(session, numbering.NumberKind.OUTGOING, now)
    document.status, document.updated_at = DocumentStatus.SENT.value, now
    await journal.record(session, "document.sent", by=employee.crm_user_id, document_id=document.id)
    await _publish_registered(session, bus, document, registered_at=now, actor_id=employee.crm_user_id)
    await document_state.archive(session, bus, document, actor_id=employee.crm_user_id, reason=document.status)


async def _open_approval(
    session: AsyncSession, bus: AsyncBus, document: Document, employee: Employee, kind: DocumentKind
) -> None:
    await _check_addressee(session, kind, document.addressee_crm_user_id)
    if document.status == DocumentStatus.RETURNED.value:
        document.version += 1
    document.status, document.updated_at = DocumentStatus.ON_APPROVAL.value, clock.now()
    await _snapshot(session, document, employee)
    rounds = await session.execute(
        select(func.count()).select_from(ApprovalRoute).where(ApprovalRoute.document_id == document.id)
    )
    template = _TEMPLATE[kind]
    await approvals.open_route(
        session,
        bus,
        template=template,
        title=f"{document.number} · {document.subject}",
        steps=approvals.steps_for(
            template, addressee=document.addressee_crm_user_id, with_amount=document.amount is not None
        ),
        actor_id=employee.crm_user_id,
        round_no=int(rounds.scalar_one()) + 1,
        document=document,
    )
    await journal.record(
        session, "document.submitted", by=employee.crm_user_id, document_id=document.id, version=document.version
    )
