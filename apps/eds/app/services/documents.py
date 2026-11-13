"""Документы EDS: служебная записка, заявление, отчёт, исходящее письмо (SPEC-v3 §3.2; eds.yaml, тег `documents`).

`memo`/`application`/`report`: номер (`СЗ|ЗЯ|ОТ-ГГГГ/NNN`) — при создании, `document.registered`; отправка открывает
круг маршрута (`approval.requested`), после возврата версия растёт. `letter_out`: номер `ИСХ-NNN/ГГ` — при регистрации,
затем архив.

Письмо на бланке (P4): тело блоками (`letter`), PDF — фоновый рендер (`services/renders.py`), «Отправить адресату» —
`services/letter_mail.py`. Черновик письма создаёт любой с `memos.create` (исполнитель «Подготовить ответ», B-P8B-4) и
передаёт делопроизводителю (`request_registration`); регистрирует только `letters.register` — автор или, если черновик
передан, любой держатель права.
"""

import secrets
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.config import get_settings
from app.errors import conflict, forbidden, forbidden_reason, invalid_fields, not_found
from app.models import ApprovalRoute, Document, DocumentVersion, Employee, Letter
from app.schemas.approvals import ApprovalTemplate
from app.schemas.common import Money
from app.schemas.documents import (
    DocumentCreate,
    DocumentKind,
    DocumentStatus,
    DocumentSubmitIn,
    DocumentUpdate,
    OutgoingLetterIn,
)
from app.security.permissions import EdsPermission as P
from app.services import (
    access,
    approvals,
    document_state,
    events,
    files,
    instructions,
    journal,
    letter_body,
    letter_mail,
    numbering,
    renders,
    reply,
    signing_resolve,
)
from app.services.employees import get_employee
from app.services.people import holds_permission, load_directory
from app.services.storage import ObjectStorage

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

# Пункт 1.6 плана: подпись шага согласующего, которого добавил автор (шаблонные — «Директор», «Бухгалтер»).
APPROVER = "Согласующий"


def required_permission(kind: DocumentKind) -> P:
    """Отправка: `letter_out` регистрирует регистратор писем, остальное отправляет любой с `memos.create`."""
    return P.LETTERS_REGISTER if kind is DocumentKind.LETTER_OUT else P.MEMOS_CREATE


def require_kind_permission(employee: Employee, kind: DocumentKind) -> None:
    needed = required_permission(kind)
    if not access.has(employee, needed):
        raise forbidden((needed.value,))


def require_draft_permission(employee: Employee, kind: DocumentKind) -> None:
    """Черновик: любой тип — `memos.create`; черновик письма — ещё и `letters.register` (P4, B-P8B-4)."""
    allowed = (P.MEMOS_CREATE, P.LETTERS_REGISTER) if kind is DocumentKind.LETTER_OUT else (P.MEMOS_CREATE,)
    if not any(access.has(employee, permission) for permission in allowed):
        raise forbidden(tuple(permission.value for permission in allowed))


def _apply_letter(document: Document, letter: OutgoingLetterIn | None) -> None:
    """Письмо на бланке: тело (проверено `rt_docs`), «кому», почта, подписант; `text` — производный от тела."""
    if letter is None:
        document.body = None
        document.recipient_attention = document.recipient_email = None
        document.signatory_name = document.signatory_position = None
        return
    document.body = letter_body.clean(letter.body)
    document.text = letter_body.plain_text(document.body)
    document.recipient_attention = (letter.recipient_attention or "").strip() or None
    document.recipient_email = (letter.recipient_email or "").strip() or None
    document.signatory_name = (letter.signatory_name or "").strip() or None
    document.signatory_position = (letter.signatory_position or "").strip() or None


def _check_amount(amount: Money | None) -> None:
    if amount is not None and Decimal(amount.amount) <= 0:
        raise invalid_fields("Сумма должна быть больше нуля.", amount="must_be_positive")


async def _check_addressee(session: AsyncSession, kind: DocumentKind, addressee: int | None, author: int) -> None:
    """Адресат решает первый шаг: активный сотрудник с `memos.approve` и не сам автор (разделение обязанностей)."""
    if addressee is None or kind is DocumentKind.LETTER_OUT:
        return
    if addressee == author:
        raise invalid_fields("Нельзя адресовать документ самому себе.", addressee_crm_user_id="same_as_author")
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


def generate_verification_code(length: int = 10) -> str:
    """Случайный криптографический код проверки подлинности (ADR-0024 п. 5): 10 символов."""
    alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _publish_signed(
    session: AsyncSession,
    bus: AsyncBus,
    document: Document,
    *,
    signed_at: datetime,
    verification_code: str,
    verification_url: str,
    actor_id: int,
) -> None:
    ids = [
        document.author_crm_user_id,
        document.signed_by_crm_user_id,
        document.acting_for_crm_user_id,
    ]
    directory = await load_directory(session, [i for i in ids if i is not None])
    body: dict[str, Any] = {
        "eds_document_id": str(document.id),
        "kind": document.kind,
        "number": document.number,
        "subject": document.subject,
        "author": directory.person(document.author_crm_user_id).model_dump(),
        "signer": directory.person(document.signed_by_crm_user_id).model_dump()
        if document.signed_by_crm_user_id
        else directory.person(actor_id).model_dump(),
        "authority_id": str(document.signing_authority_id) if document.signing_authority_id else None,
        "basis": document.signatory_basis or "charter",
        "basis_text": document.signatory_basis_text,
        "acting_for": (
            directory.person(document.acting_for_crm_user_id).model_dump() if document.acting_for_crm_user_id else None
        ),
        "signed_at": signed_at.isoformat(),
        "verification_code": verification_code,
        "verification_url": verification_url,
        "pdf_hash": document.pdf_hash,
        "dispatch_method": document.dispatch_method or "email",
        "in_reply_to": str(document.in_reply_to) if document.in_reply_to else None,
        "erp_deal_id": document.erp_deal_id,
        "deal_number": document.deal_number,
    }
    await events.publish(
        bus,
        session,
        "document.signed",
        {"document": body, "actor": events.actor(actor_id)},
        subject=str(document.number),
    )


async def create(session: AsyncSession, bus: AsyncBus, *, employee: Employee, data: DocumentCreate) -> Document:
    """Черновик документа. `memo`/`application`/`report` получают номер сразу, `letter_out` — при отправке."""
    require_draft_permission(employee, data.kind)
    is_letter = data.kind is DocumentKind.LETTER_OUT
    if not is_letter and (data.recipient is not None or data.in_reply_to is not None or data.letter is not None):
        raise invalid_fields("Адресат и ответ на письмо — только у исходящего письма.", recipient="letter_out_only")
    _check_amount(data.amount)
    await _check_addressee(session, data.kind, data.addressee_crm_user_id, employee.crm_user_id)
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
    if is_letter and data.letter is not None:
        _apply_letter(document, data.letter)
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


async def update(
    session: AsyncSession, *, employee: Employee, document_id: uuid.UUID, edits: DocumentUpdate
) -> Document:
    """Править черновик (или возвращённый документ) без отправки. Только автор; другой статус — 409 `invalid_state`."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    kind = DocumentKind(document.kind)
    require_draft_permission(employee, kind)
    if document.author_crm_user_id != employee.crm_user_id:
        raise forbidden_reason("not_author", "Править документ может только его автор.")
    allowed = {DocumentStatus.DRAFT.value} if kind is DocumentKind.LETTER_OUT else {"draft", "returned"}
    if document.status not in allowed:
        raise conflict("invalid_state", "Документ нельзя править в текущем статусе.", status=document.status)
    _check_amount(edits.amount)
    _apply_edits(document, edits)
    if "erp_deal_id" in edits.model_fields_set:
        document.erp_deal_id = edits.erp_deal_id
        document.deal_number = await deal_number_for(session, edits.erp_deal_id)
    if "recipient" in edits.model_fields_set:
        if kind is not DocumentKind.LETTER_OUT:
            if edits.recipient is not None:
                raise invalid_fields("Адресат — только у исходящего письма.", recipient="letter_out_only")
        else:
            document.recipient_name = edits.recipient.name if edits.recipient else None
            document.recipient_inn = edits.recipient.inn if edits.recipient else None
    if "letter" in edits.model_fields_set:
        if kind is not DocumentKind.LETTER_OUT:
            if edits.letter is not None:
                raise invalid_fields("Письмо на бланке — только у исходящего письма.", letter="letter_out_only")
        else:
            _apply_letter(document, edits.letter)
    document.updated_at = clock.now()
    if edits.file_ids:
        await files.attach(session, edits.file_ids, actor_id=employee.crm_user_id, document_id=document.id)
    await journal.record(session, "document.updated", by=employee.crm_user_id, document_id=document.id)
    return document


def _may_register(employee: Employee, document: Document) -> bool:
    """Чужое письмо регистрирует держатель `letters.register`, если автор передал черновик на регистрацию (B-P8B-4)."""
    return (
        document.kind == DocumentKind.LETTER_OUT.value
        and document.registration_requested_at is not None
        and access.has(employee, P.LETTERS_REGISTER)
    )


async def submit(
    session: AsyncSession,
    bus: AsyncBus,
    *,
    employee: Employee,
    document_id: uuid.UUID,
    edits: DocumentSubmitIn | None,
    storage: ObjectStorage | None = None,
) -> Document:
    """Отправить на согласование (или зарегистрировать исходящее письмо). Автор (письмо — ещё делопроизводитель, если
    черновик передан на регистрацию); другой статус — 409 `invalid_state`."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    kind = DocumentKind(document.kind)
    require_kind_permission(employee, kind)
    if document.author_crm_user_id != employee.crm_user_id and not _may_register(employee, document):
        raise forbidden_reason("not_author", "Отправить документ может только его автор.")
    allowed = {DocumentStatus.DRAFT.value} if kind is DocumentKind.LETTER_OUT else {"draft", "returned"}
    if document.status not in allowed:
        raise conflict("invalid_state", "Документ нельзя отправить в текущем статусе.", status=document.status)
    changes = edits or DocumentSubmitIn()
    _check_amount(changes.amount)
    _apply_edits(document, changes)
    if kind is not DocumentKind.LETTER_OUT:
        await _apply_route_people(session, document, changes)
    if changes.file_ids:
        await files.attach(session, changes.file_ids, actor_id=employee.crm_user_id, document_id=document.id)
    if kind is DocumentKind.LETTER_OUT:
        if changes.send and not (document.recipient_email and document.body is not None):
            raise invalid_fields("Укажите почту адресата и текст письма на бланке.", recipient_email="required")
        await _send_letter(session, bus, document, employee)
        if document.body is not None:
            render = await renders.request(session, document)
            if changes.send:
                await letter_mail.start(
                    session, bus, _storage(storage), document=document, render=render, actor_id=employee.crm_user_id
                )
    else:
        await _open_approval(session, bus, document, employee, kind)
    return document


async def sign(
    session: AsyncSession,
    bus: AsyncBus,
    *,
    employee: Employee,
    document_id: uuid.UUID,
    authority_id: uuid.UUID | None = None,
    dispatch_method: str = "email",
    send: bool = True,
    storage: ObjectStorage | None = None,
) -> Document:
    """Подписание документа уполномоченным лицом из реестра полномочий (SIGN-3, ADR-0024 п. 1–5)."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    if document.status not in (DocumentStatus.DRAFT.value, DocumentStatus.RETURNED.value):
        raise conflict("invalid_state", "Документ нельзя подписать в текущем статусе.", status=document.status)

    now = clock.now()
    today = clock.company_date(now)

    check_result = await signing_resolve.check_signer(
        session,
        employee.crm_user_id,
        kind=document.kind,
        amount=document.amount,
        currency=document.currency,
        on_date=today,
    )
    if not check_result.allowed or check_result.candidate is None:
        raise forbidden_reason(check_result.reason or "no_authority", check_result.message)

    candidate = check_result.candidate
    if authority_id is not None and candidate.authority.id != authority_id:
        res = await signing_resolve.resolve(
            session,
            kind=document.kind,
            amount=document.amount,
            currency=document.currency,
            on_date=today,
        )
        matched = [
            c for c in res.candidates if c.authority.id == authority_id and c.signer.crm_user_id == employee.crm_user_id
        ]
        if not matched:
            raise conflict(
                "authority_mismatch", "Выбранное полномочие не действительно или не соответствует документу."
            )
        candidate = matched[0]

    # Правило «автор ≠ подписант» (ADR-0024 п. 3):
    if document.author_crm_user_id == employee.crm_user_id:
        res = await signing_resolve.resolve(
            session,
            kind=document.kind,
            amount=document.amount,
            currency=document.currency,
            on_date=today,
        )
        other_candidates = [c for c in res.candidates if c.signer.crm_user_id != employee.crm_user_id]
        if other_candidates:
            raise conflict(
                "author_cannot_sign",
                "Автор проекта письма не вправе подписывать документ при наличии других лиц с правом подписи.",
            )

    method = dispatch_method if dispatch_method in ("email", "paper", "courier", "edo", "other") else "email"
    if method == "email" and send and not (document.recipient_email and document.body is not None):
        raise invalid_fields("Укажите почту адресата и текст письма на бланке.", recipient_email="required")

    if not document.number:
        document.number = await numbering.allocate(session, numbering.NumberKind.OUTGOING, now)

    verification_code = generate_verification_code()
    verification_url = f"https://{get_settings().cabinet_domain}/v/{verification_code}"

    document.status = DocumentStatus.SENT.value
    document.signed_at = now
    document.registered_at = now
    document.updated_at = now
    document.signed_by_crm_user_id = employee.crm_user_id
    document.signing_authority_id = candidate.authority.id if candidate.authority else None
    document.signatory_basis = candidate.authority.basis if candidate.authority else None
    document.signatory_basis_text = candidate.basis_text
    document.acting_for_crm_user_id = candidate.acting_for[0].crm_user_id if candidate.acting_for else None
    document.verification_code = verification_code
    document.dispatch_method = method
    document.signatory_name = candidate.signer.full_name
    document.signatory_position = candidate.position

    await journal.record(
        session,
        "document.signed",
        by=employee.crm_user_id,
        document_id=document.id,
        comment=f"Подписан исходящий документ {document.number}. Основание: {document.signatory_basis_text}.",
    )

    render = None
    if document.body is not None:
        render = await renders.request(session, document)
        document.pdf_hash = render.hash

    await _publish_signed(
        session,
        bus,
        document,
        signed_at=now,
        verification_code=verification_code,
        verification_url=verification_url,
        actor_id=employee.crm_user_id,
    )
    await _publish_registered(session, bus, document, registered_at=now, actor_id=employee.crm_user_id)
    await document_state.archive(session, bus, document, actor_id=employee.crm_user_id, reason=document.status)

    closed = await instructions.close_by_outgoing(session, bus, document=document, actor_id=employee.crm_user_id)
    await reply.notify_registered(session, bus, document, closed_executors=closed, actor_id=employee.crm_user_id)

    if method == "email" and send and render is not None:
        await letter_mail.start(
            session, bus, _storage(storage), document=document, render=render, actor_id=employee.crm_user_id
        )

    return document


async def get_for_pdf(session: AsyncSession, *, employee: Employee, document_id: uuid.UUID) -> Document:
    """PDF на бланке строит автор письма; держатель `letters.register` — переданный черновик и зарегистрированное."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    if document.kind != DocumentKind.LETTER_OUT.value:
        raise conflict("no_body", "PDF на бланке строится только для письма.")
    if not may_open_pdf(employee, document):
        raise forbidden_reason("not_author", "PDF письма строит его автор или делопроизводитель.")
    return document


def may_open_pdf(employee: Employee, document: Document) -> bool:
    """Кто строит и скачивает PDF проекта (SIGN-1, ADR-0024 п. 4): автор письма; держатель `letters.register` —
    переданный ему черновик и зарегистрированное письмо. Маршрута у письма нет; появится — его участники добавляются
    сюда же. Итоговый PDF открывается по видимости документа."""
    mine = document.author_crm_user_id == employee.crm_user_id
    registrar = access.has(employee, P.LETTERS_REGISTER) and (
        document.status == DocumentStatus.SENT.value or document.registration_requested_at is not None
    )
    return mine or registrar


def _storage(storage: ObjectStorage | None) -> ObjectStorage:
    if storage is None:
        from app.container import get_container  # API передаёт хранилище; без него — хранилище процесса

        return get_container().storage
    return storage


async def request_registration(
    session: AsyncSession, bus: AsyncBus, *, employee: Employee, document_id: uuid.UUID
) -> Document:
    """«Передать на регистрацию» (B-P8B-4): автор черновика письма просит делопроизводителя зарегистрировать ИСХ."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    if document.kind != DocumentKind.LETTER_OUT.value:
        raise conflict("invalid_state", "На регистрацию передаётся только исходящее письмо.", status=document.status)
    require_draft_permission(employee, DocumentKind.LETTER_OUT)
    if document.author_crm_user_id != employee.crm_user_id:
        raise forbidden_reason("not_author", "Передать письмо может только его автор.")
    if document.status != DocumentStatus.DRAFT.value:
        raise conflict("invalid_state", "Письмо уже зарегистрировано.", status=document.status)
    if document.body is None:
        raise conflict("no_body", "Сначала напишите текст письма на бланке.")
    if document.registration_requested_at is None:
        now = clock.now()
        document.registration_requested_by, document.registration_requested_at = employee.crm_user_id, now
        document.updated_at = now
        await journal.record(
            session, "document.registration_requested", by=employee.crm_user_id, document_id=document.id
        )
        await reply.notify_registration_requested(session, bus, document, actor_id=employee.crm_user_id)
    return document


async def send_again(
    session: AsyncSession, bus: AsyncBus, storage: ObjectStorage, *, employee: Employee, document_id: uuid.UUID
) -> Document:
    """Повтор «Отправить адресату» зарегистрированного письма на бланке (например, после настройки почты)."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    if document.kind != DocumentKind.LETTER_OUT.value or document.status != DocumentStatus.SENT.value:
        raise conflict("invalid_state", "Отправить адресату можно зарегистрированное письмо.", status=document.status)
    if document.body is None:
        raise conflict("no_body", "У письма нет PDF на бланке.")
    render = await renders.request(session, document)
    await letter_mail.start(session, bus, storage, document=document, render=render, actor_id=employee.crm_user_id)
    return document


async def _send_letter(session: AsyncSession, bus: AsyncBus, document: Document, employee: Employee) -> None:
    now = clock.now()
    document.number = await numbering.allocate(session, numbering.NumberKind.OUTGOING, now)
    document.status, document.updated_at, document.registered_at = DocumentStatus.SENT.value, now, now
    await journal.record(session, "document.sent", by=employee.crm_user_id, document_id=document.id)
    await _publish_registered(session, bus, document, registered_at=now, actor_id=employee.crm_user_id)
    await document_state.archive(session, bus, document, actor_id=employee.crm_user_id, reason=document.status)
    # P8b: ИСХ «в ответ на ВХ» закрывает поручения «Подготовить ответ» этого письма (тот же хук — письмо на бланке P4).
    closed = await instructions.close_by_outgoing(session, bus, document=document, actor_id=employee.crm_user_id)
    await reply.notify_registered(session, bus, document, closed_executors=closed, actor_id=employee.crm_user_id)


async def _apply_route_people(session: AsyncSession, document: Document, changes: DocumentSubmitIn) -> None:
    """Пункт 1.6 плана: согласующие и получатели копии от автора. Не переданы — остаются прежние (повторная отправка
    после возврата). Только активные сотрудники, без повторов и без самого автора; иначе 422 с полем."""
    for field, wanted in (("approvers", changes.approvers), ("watchers", changes.watchers)):
        if wanted is None:
            continue
        people = list(dict.fromkeys(wanted))
        if document.author_crm_user_id in people:
            raise invalid_fields("Автор не может быть в этом списке.", **{field: "author_not_allowed"})
        for uid in people:
            person = await get_employee(session, uid)
            if person is None or not person.is_active:
                raise invalid_fields("Выберите действующего сотрудника.", **{field: "not_active_employee"})
        setattr(document, "extra_approvers" if field == "approvers" else "watchers", people)


async def _open_approval(
    session: AsyncSession, bus: AsyncBus, document: Document, employee: Employee, kind: DocumentKind
) -> None:
    await _check_addressee(session, kind, document.addressee_crm_user_id, document.author_crm_user_id)
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
        # Пункт 1.6: согласующие автора — перед шагами шаблона, по порядку.
        steps=[approvals.StepSpec(APPROVER, crm_user_id=uid) for uid in document.extra_approvers or []]
        + approvals.steps_for(
            template, addressee=document.addressee_crm_user_id, with_amount=document.amount is not None
        ),
        actor_id=employee.crm_user_id,
        round_no=int(rounds.scalar_one()) + 1,
        document=document,
    )
    await journal.record(
        session, "document.submitted", by=employee.crm_user_id, document_id=document.id, version=document.version
    )
