"""Документы EDS: служебная записка, заявление, отчёт, исходящее письмо (SPEC-v3 §3.2; eds.yaml, тег `documents`).

`memo`/`application`/`report`: номер (`СЗ|ЗЯ|ОТ-ГГГГ/NNN`) — при создании, `document.registered`; отправка открывает
круг маршрута (`approval.requested`), после возврата версия растёт. `letter_out`: номер `ИСХ-NNN/ГГ` выдаёт только
подписание (`sign`, в том числе бумажное: `dispatch_method=paper`), затем архив;
`submit` без подписи — 409 `signature_required`.

Письмо на бланке (P4): тело блоками (`letter`), PDF — фоновый рендер (`services/renders.py`), «Отправить адресату» —
`services/letter_mail.py`. Черновик письма создаёт любой с `memos.create` (исполнитель «Подготовить ответ», B-P8B-4) и
передаёт на подпись (`request_registration`); подписывает вычисленный подписант (`services/signing`).
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.config import get_settings
from app.errors import EdsError, conflict, forbidden, forbidden_reason, invalid_fields, not_found
from app.models import ApprovalRoute, Document, DocumentVersion, Employee, JournalEntry, Letter
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
from app.schemas.signing import SignerCandidate
from app.security.permissions import EdsPermission as P
from app.services import (
    access,
    approvals,
    docflow_settings,
    document_notices,
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
    signing_state,
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
#: «Напомнить» подписанту — не чаще раза в этот срок (ГЛ-0)
REMIND_INTERVAL = timedelta(hours=1)
# One journal fact for "the signer of this letter was reminded": the letter card (GL-0) and the waiting list (GL-1)
# both write and read it, so a reminder through either path blocks the other for an hour.
SIGN_REMINDED = "document.sign_reminded"


def required_permission(kind: DocumentKind) -> P:
    """Отправка: `letter_out` — держатель `letters.register` (номер даёт `sign`), прочее — любой с `memos.create`."""
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


async def _apply_letter(session: AsyncSession, document: Document, letter: OutgoingLetterIn | None) -> None:
    """Письмо на бланке: тело (проверено `rt_docs`), «кому», почта, подписант; `text` — производный от тела."""
    if letter is None:
        document.body = None
        document.recipient_attention = document.recipient_email = None
        document.signatory_name = document.signatory_position = None
        document.chosen_signer_crm_user_id = None
        return
    document.body = letter_body.clean(letter.body)
    document.text = letter_body.plain_text(document.body)
    document.recipient_attention = (letter.recipient_attention or "").strip() or None
    document.recipient_email = (letter.recipient_email or "").strip() or None
    document.signatory_name = (letter.signatory_name or "").strip() or None
    document.signatory_position = (letter.signatory_position or "").strip() or None
    await _apply_chosen_signer(session, document, letter.signer_crm_user_id)


async def _apply_chosen_signer(session: AsyncSession, document: Document, signer_id: int | None) -> None:
    """ЕД-6: подписант выбран — имя берётся из справочника сотрудников, должность — оттуда же, если автор не вписал свою
    (для «и. о.»; справочник не меняется). Выбрать можно только держателя действующего полномочия на письма."""
    previous = document.chosen_signer_crm_user_id
    document.chosen_signer_crm_user_id = signer_id
    if signer_id is None:
        return
    if signer_id == previous:
        # An unchanged saved choice is accepted even if the right was revoked since: routing re-checks at send time
        # (pick_letter_signer), and the draft must stay editable.
        return
    today = clock.company_date(clock.now())
    options = {o.crm_user_id: o for o in await signing_resolve.letter_signer_options(session, today)}
    option = options.get(signer_id)
    if option is None:
        raise invalid_fields("Выберите подписанта с правом подписи.", signer_crm_user_id="no_signing_right")
    others = [uid for uid in options if uid != document.author_crm_user_id]
    may_sign_own = await docflow_settings.author_may_sign_own_letter(session)
    if signer_id == document.author_crm_user_id and others and not may_sign_own:
        raise invalid_fields("Автор письма не подписывает его сам.", signer_crm_user_id="author_cannot_sign")
    document.signatory_name = option.full_name
    document.signatory_position = document.signatory_position or option.position


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
    if document.kind == DocumentKind.LETTER_OUT.value:
        body["letter"] = await _letter_block(session, document)
    await events.publish(
        bus,
        session,
        "document.registered",
        {"document": body, "actor": events.actor(actor_id)},
        subject=str(document.number),
    )


async def _letter_block(session: AsyncSession, document: Document) -> dict[str, Any]:
    """Блок `document.letter` исходящего письма (ЛИД-8, ADR-0026): кому и в ответ на какое входящее. По нему ERP кладёт
    письмо в кабинет компании-получателя — только по сделке или точному ИНН."""
    reply_to = await session.get(Letter, document.in_reply_to) if document.in_reply_to else None
    return {
        "recipient": {
            "name": document.recipient_name,
            "inn": document.recipient_inn or None,
            "email": document.recipient_email,
        },
        "in_reply_to": None if reply_to is None else {"eds_letter_id": str(reply_to.id), "number": reply_to.number},
    }


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
    """Черновик документа. `memo`/`application`/`report` получают номер сразу, `letter_out` — в `sign`."""
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
        invoice_later=data.invoice_later,
        source_message_id=data.source_message_id,
        erp_deal_id=data.erp_deal_id,
        deal_number=await deal_number_for(session, data.erp_deal_id),
        recipient_name=data.recipient.name if data.recipient else None,
        recipient_inn=data.recipient.inn if data.recipient else None,
        recipient_company_id=data.recipient.company_id if data.recipient else None,
        recipient_contact_id=data.recipient.contact_id if data.recipient else None,
        in_reply_to=data.in_reply_to,
        created_at=now,
        updated_at=now,
    )
    if is_letter and data.letter is not None:
        await _apply_letter(session, document, data.letter)
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
    if edits.invoice_later is not None:
        document.invoice_later = edits.invoice_later


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


async def _signer_id(session: AsyncSession, document: Document) -> int | None:
    signer = await signing_resolve.letter_signer(session, document, clock.company_date(clock.now()))
    return None if signer is None else signer.signer.crm_user_id


async def update(
    session: AsyncSession,
    bus: AsyncBus,
    *,
    employee: Employee,
    document_id: uuid.UUID,
    edits: DocumentUpdate,
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
    handed = signing_state.is_awaiting_signature(document)
    signer_before = await _signer_id(session, document) if handed else None
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
            document.recipient_company_id = edits.recipient.company_id if edits.recipient else None
            document.recipient_contact_id = edits.recipient.contact_id if edits.recipient else None
    if "letter" in edits.model_fields_set:
        if kind is not DocumentKind.LETTER_OUT:
            if edits.letter is not None:
                raise invalid_fields("Письмо на бланке — только у исходящего письма.", letter="letter_out_only")
        else:
            await _apply_letter(session, document, edits.letter)
    document.updated_at = clock.now()
    if edits.file_ids:
        await files.attach(session, edits.file_ids, actor_id=employee.crm_user_id, document_id=document.id)
    await journal.record(session, "document.updated", by=employee.crm_user_id, document_id=document.id)
    if handed and await _signer_id(session, document) != signer_before:
        # ГЛ-0: на подписи сменился вычисленный подписант — новому уходит «Подпишите исходящее»
        await document_notices.letter_handed_over(
            session, bus, document, today=clock.company_date(clock.now()), actor_id=employee.crm_user_id, again=True
        )
    return document


async def submit(
    session: AsyncSession,
    bus: AsyncBus,
    *,
    employee: Employee,
    document_id: uuid.UUID,
    edits: DocumentSubmitIn | None,
    storage: ObjectStorage | None = None,
) -> Document:
    """Отправить на согласование служебный документ (автор). Исходящее письмо так не регистрируется и не уходит: номер
    и отправка — только в `sign()` (решение владельца 2026-11-21 (3)), иначе 409 `signature_required`; другой статус —
    409 `invalid_state`."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    kind = DocumentKind(document.kind)
    require_kind_permission(employee, kind)
    allowed = {DocumentStatus.DRAFT.value} if kind is DocumentKind.LETTER_OUT else {"draft", "returned"}
    if document.status not in allowed:
        raise conflict("invalid_state", "Документ нельзя отправить в текущем статусе.", status=document.status)
    if kind is DocumentKind.LETTER_OUT:
        raise conflict(
            "signature_required",
            "Исходящее письмо регистрируется и отправляется только после подписи: нажмите «Подписать».",
            status=document.status,
        )
    if document.author_crm_user_id != employee.crm_user_id:
        raise forbidden_reason("not_author", "Отправить документ может только его автор.")
    changes = edits or DocumentSubmitIn()
    _check_amount(changes.amount)
    _apply_edits(document, changes)
    await _apply_route_people(session, document, changes)
    if changes.file_ids:
        await files.attach(session, changes.file_ids, actor_id=employee.crm_user_id, document_id=document.id)
    await _open_approval(session, bus, document, employee, kind)
    return document


@dataclass(frozen=True, slots=True)
class SignCheck:
    """Итог «может ли этот сотрудник подписать это письмо сейчас»: одна проверка для кнопки и для самого действия."""

    allowed: bool
    reason: str | None
    message: str
    signer: SignerCandidate | None  # кому подпись достаётся по реестру (не обязательно спросившему)
    candidate: SignerCandidate | None  # полномочие самого спросившего, если он вправе
    state_conflict: bool = False  # отказ из-за состояния документа или правила «автор ≠ подписант» (409), иначе 403
    status: str | None = None  # статус документа при отказе по состоянию (уходит в details.status)

    def error(self) -> EdsError:
        reason = self.reason or "no_authority"
        if self.state_conflict:
            return conflict(reason, self.message, **({} if self.status is None else {"status": self.status}))
        return forbidden_reason(reason, self.message)


async def sign_check(session: AsyncSession, employee: Employee, document: Document, today: date) -> SignCheck:
    """Может ли `employee` подписать `document` на дату `today`: право Signer, вид, статус, реестр полномочий, правило
    «автор ≠ подписант» (ADR-0024 п. 3). Её вызывают `sign()` и карточка документа (`Document.signing`)."""
    if document.kind != DocumentKind.LETTER_OUT.value:
        return SignCheck(False, "invalid_state", "Подписывается только исходящее письмо.", None, None, True)
    if document.status not in (DocumentStatus.DRAFT.value, DocumentStatus.RETURNED.value):
        return SignCheck(
            False, "invalid_state", "Документ нельзя подписать в текущем статусе.", None, None, True, document.status
        )
    result = await signing_resolve.resolve(
        session, kind=document.kind, amount=document.amount, currency=document.currency, on_date=today
    )
    openers = await signing_resolve.draft_openers(session, {c.signer.crm_user_id for c in result.candidates})
    may_sign_own = await docflow_settings.author_may_sign_own_letter(session)
    signer = signing_resolve.pick_letter_signer(
        result, document.author_crm_user_id, openers, document.chosen_signer_crm_user_id, author_may_sign=may_sign_own
    )
    if not (access.has(employee, P.LETTERS_REGISTER) or access.has(employee, P.MEMOS_APPROVE)):
        return SignCheck(False, "no_permission", "Подписывать письма может сотрудник с правом подписи.", signer, None)
    own = signing_resolve.signer_check(result, employee.crm_user_id)
    if not own.allowed or own.candidate is None:
        return SignCheck(False, own.reason or "no_authority", own.message, signer, None)
    # Тот же круг, что и у вычисленного подписанта (ГЛ-0): иначе автор становится подписантом и получает отказ
    pool = signing_resolve.letter_pool(result, openers)
    if signing_resolve.author_blocked(
        pool, document.author_crm_user_id, employee.crm_user_id, author_may_sign=may_sign_own
    ):
        message = "Автор проекта письма не вправе подписывать документ при наличии других лиц с правом подписи."
        return SignCheck(False, "author_cannot_sign", message, signer, own.candidate, True)
    return SignCheck(True, None, own.message, signer, own.candidate)


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

    now = clock.now()
    today = clock.company_date(now)

    check = await sign_check(session, employee, document, today)
    if not check.allowed or check.candidate is None:
        raise check.error()

    candidate = check.candidate
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
    if document.chosen_signer_crm_user_id != employee.crm_user_id or not document.signatory_position:
        document.signatory_position = candidate.position  # «и. о.», вписанное автором, остаётся

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
    await document_notices.letter_signed(
        session, bus, document, signer_id=employee.crm_user_id, signer_name=candidate.signer.full_name
    )

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
        await document_notices.letter_handed_over(
            session,
            bus,
            document,
            today=clock.company_date(now),
            actor_id=employee.crm_user_id,
        )
    return document


def _own_awaiting_letter(employee: Employee, document: Document) -> None:
    """Письмо на подписи и действие автора над ним: другой вид, статус или не автор — отказ."""
    if document.kind != DocumentKind.LETTER_OUT.value:
        raise conflict("invalid_state", "Действие доступно только для исходящего письма.", status=document.status)
    if document.author_crm_user_id != employee.crm_user_id:
        raise forbidden_reason("not_author", "Это может сделать только автор письма.")
    if not signing_state.is_awaiting_signature(document):
        raise conflict("not_handed_over", "Письмо не передано на подпись.", status=document.status)


async def remind_signer(
    session: AsyncSession, bus: AsyncBus, *, employee: Employee, document_id: uuid.UUID
) -> Document:
    """«Напомнить» (ГЛ-0): подписанту письма на подписи повторно уходит «Подпишите исходящее»; не чаще раза в час —
    факт берётся из журнала (`SIGN_REMINDED`, общий с «Вы ждёте других»), отдельного поля нет."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    _own_awaiting_letter(employee, document)
    now = clock.now()
    last = (
        await session.execute(
            select(func.max(JournalEntry.at)).where(
                JournalEntry.document_id == document.id, JournalEntry.action == SIGN_REMINDED
            )
        )
    ).scalar_one()
    if last is not None and now - last < REMIND_INTERVAL:
        raise conflict(
            "remind_too_soon",
            "Напоминание уже отправлено. Повторить можно через час.",
            retry_at=(last + REMIND_INTERVAL).isoformat(),
        )
    await journal.record(session, SIGN_REMINDED, by=employee.crm_user_id, document_id=document.id)
    await document_notices.letter_handed_over(
        session, bus, document, today=clock.company_date(now), actor_id=employee.crm_user_id, again=True
    )
    return document


async def withdraw_from_signing(
    session: AsyncSession, bus: AsyncBus, *, employee: Employee, document_id: uuid.UUID
) -> Document:
    """«Отозвать» (ГЛ-0): передача снята — письмо снова черновик автора. Очередь подписанта выводится из факта передачи,
    поэтому задача у него пропадает сама."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    _own_awaiting_letter(employee, document)
    signer_id = await _signer_id(session, document)  # before the handover is cleared
    document.registration_requested_at = document.registration_requested_by = None
    document.updated_at = clock.now()
    await journal.record(
        session,
        "document.registration_withdrawn",
        by=employee.crm_user_id,
        document_id=document.id,
        comment="Отозвано с подписи",
    )
    await document_notices.letter_withdrawn(session, bus, document, signer_id=signer_id, actor_id=employee.crm_user_id)
    return document


async def change_signer(
    session: AsyncSession,
    bus: AsyncBus,
    *,
    employee: Employee,
    document_id: uuid.UUID,
    signer_id: int | None,
) -> Document:
    """«Сменить подписанта» (ГЛ-0): автор выбирает другого подписанта письма на подписи; новому уходит «Подпишите
    исходящее». Выбор проверяет та же `_apply_chosen_signer`, что при правке черновика (право, правило автора)."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    _own_awaiting_letter(employee, document)
    before = await _signer_id(session, document)
    await _apply_chosen_signer(session, document, signer_id)
    document.updated_at = clock.now()
    after = await _signer_id(session, document)
    if after != before:
        who = None if after is None else (await get_employee(session, after))
        await journal.record(
            session,
            "document.signer_changed",
            by=employee.crm_user_id,
            document_id=document.id,
            comment=None if who is None else f"Подписант: {who.full_name}",
        )
        await document_notices.letter_handed_over(
            session, bus, document, today=clock.company_date(clock.now()), actor_id=employee.crm_user_id, again=True
        )
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


async def waive_mail(session: AsyncSession, *, employee: Employee, document_id: uuid.UUID) -> Document:
    """«Вручено иначе» (СЦ-1): письмо передано адресату не почтой — отправка снята, письмо уходит в «Архив»."""
    document = await get_for_update(session, document_id)
    if not await access.can_view_document(session, employee, document.id):
        raise not_found("Документ не найден.")
    if document.kind != DocumentKind.LETTER_OUT.value or document.status != DocumentStatus.SENT.value:
        raise conflict("invalid_state", "Отметить можно зарегистрированное письмо.", status=document.status)
    if document.mail_waived_at is None:
        document.mail_waived_at, document.mail_waived_by = clock.now(), employee.crm_user_id
        await journal.record(session, "document.mail_waived", by=employee.crm_user_id, document_id=document.id)
    return document


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
