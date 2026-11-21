"""Путь «ответ на входящее» (EDS-REPLY-1): связь ВХ ↔ ИСХ с обеих сторон, задача делопроизводителю, уведомления.

Исполнитель поручения «Подготовить ответ» создаёт письмо `letter_out` с `in_reply_to` (ВХ); дальше путь не обрывается:

* «Передать на регистрацию» — подписанту уходит «Подпишите исходящее» (`document_notices.letter_handed_over`) и строка в
  `GET /letter-tasks` (`signatures`; `registrations` пуст с 2026-11-21: письмо без подписи не регистрируется,
  делопроизводителям «Зарегистрируйте ответ» не шлётся — выполнить это действие сервер не даст);
* регистрация ИСХ закрывает поручение (`instructions.close_by_outgoing`) и сообщает исполнителю и автору ответа;
* письмо не ушло адресату (`crm.mail.failed`, «почта не настроена») — уведомление автору и делопроизводителям;
* карточка ВХ показывает ответы (`replies`: черновик → передан → ИСХ → итог отправки), карточка ИСХ — «в ответ на ВХ-…».

Уведомления — `notice.requested` (виды те же, что у поручений: контракт v1 их не расширяет); письмо без ВХ
уведомлений не порождает — `letter` в событии обязателен (docs/QUESTIONS.md, Q-EDS-REPLY-1).
"""

import datetime as dt
import uuid
from collections.abc import Iterable
from decimal import Decimal

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import any_, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentMailing, Employee, Letter
from app.schemas.documents import DocumentKind, DocumentStatus
from app.schemas.letters import (
    LetterReply,
    LetterReplyMail,
    LetterReplyState,
    ReplyToLetter,
    SignatureTask,
)
from app.schemas.signing import SignerCandidate, SigningResolution
from app.security.permissions import EdsPermission as P
from app.services import access, instructions, signing_resolve
from app.services.people import load_directory

REPLIES_LIMIT = 10
TASKS_LIMIT = instructions.TASKS_LIMIT
_SENDING = ("awaiting_pdf", "requested")


async def reply_to_ref(session: AsyncSession, letter_id: uuid.UUID | None) -> ReplyToLetter | None:
    """Входящее, на которое отвечает ИСХ, для карточки документа."""
    if letter_id is None:
        return None
    row = (await session.execute(select(Letter.number, Letter.subject).where(Letter.id == letter_id))).first()
    return None if row is None else ReplyToLetter(id=letter_id, number=row.number, subject=row.subject)


def _state(document: Document) -> LetterReplyState:
    if document.status == DocumentStatus.SENT.value:
        return LetterReplyState.REGISTERED
    if document.registration_requested_at is not None:
        return LetterReplyState.REGISTRATION_REQUESTED
    return LetterReplyState.DRAFT


def mail_state(last: DocumentMailing | None) -> tuple[LetterReplyMail, str | None]:
    """Итог по последней попытке отправки: нет попыток — `none`; идёт — `sending`; иначе `sent`/`failed` с причиной."""
    if last is None:
        return LetterReplyMail.NONE, None
    if last.status in _SENDING:
        return LetterReplyMail.SENDING, None
    if last.status == "failed":
        return LetterReplyMail.FAILED, last.reason
    return LetterReplyMail.SENT, None


async def _last_mailings(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, DocumentMailing]:
    rows = await session.execute(
        select(DocumentMailing)
        .where(DocumentMailing.document_id.in_(list(ids)))
        .order_by(DocumentMailing.requested_at, DocumentMailing.id)
    )
    return {m.document_id: m for m in rows.scalars()}  # поздняя попытка перекрывает раннюю


async def replies_for(session: AsyncSession, employee: Employee | None, letter: Letter) -> list[LetterReply]:
    """Ответы на входящее, видимые смотрящему (чужой черновик скрыт правилом видимости документов); новейший первым."""
    if employee is None:
        return []
    documents = list(
        (
            await session.execute(
                select(Document)
                .where(
                    Document.kind == DocumentKind.LETTER_OUT.value,
                    Document.in_reply_to == letter.id,
                    access.document_visible(employee),
                )
                .order_by(Document.created_at.desc(), Document.id)
                .limit(REPLIES_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    if not documents:
        return []
    mailings = await _last_mailings(session, (d.id for d in documents))
    directory = await load_directory(session, (d.author_crm_user_id for d in documents))
    out: list[LetterReply] = []
    for document in documents:
        mail, reason = mail_state(mailings.get(document.id))
        out.append(
            LetterReply(
                document_id=document.id,
                number=document.number,
                subject=document.subject,
                state=_state(document),
                author=directory.person(document.author_crm_user_id),
                mail=mail,
                mail_reason=reason,
                created_at=document.created_at,
            )
        )
    return out


async def signing_tasks(session: AsyncSession, employee: Employee, today: dt.date) -> list[SignatureTask]:
    """«Подписать ИСХ»: переданные черновики, подписант которых по реестру — этот сотрудник (или он по замещению)."""
    # Переданные неподписанные черновики — набор маленький, без LIMIT: обрезаем после фильтра «подписант — я».
    documents = list(
        (
            await session.execute(
                select(Document)
                .where(
                    Document.kind == DocumentKind.LETTER_OUT.value,
                    Document.status == DocumentStatus.DRAFT.value,
                    Document.registration_requested_at.is_not(None),
                    Document.registration_requested_by.is_not(None),
                )
                .order_by(Document.registration_requested_at, Document.id)
            )
        )
        .scalars()
        .all()
    )
    if not documents:
        return []
    grants, people = await signing_resolve.load_registry(session, DocumentKind.LETTER_OUT.value)
    openers = await signing_resolve.draft_openers(session, set(people))
    resolutions: dict[tuple[str, Decimal | None, str | None], SigningResolution] = {}
    mine: list[tuple[Document, SignerCandidate]] = []
    for document in documents:
        key = (document.kind, document.amount, document.currency)
        if key not in resolutions:
            resolutions[key] = signing_resolve.evaluate(
                kind=document.kind,
                amount=document.amount,
                currency=document.currency,
                on_date=today,
                grants=grants,
                people=people,
            )
        signer = signing_resolve.pick_letter_signer(resolutions[key], document.author_crm_user_id, openers)
        if signer is not None and signer.signer.crm_user_id == employee.crm_user_id:
            mine.append((document, signer))
    mine = mine[:TASKS_LIMIT]
    directory = await load_directory(session, (d.registration_requested_by for d, _ in mine))
    reply_ids = {d.in_reply_to for d, _ in mine if d.in_reply_to is not None}
    replies = {
        row.id: row
        for row in (
            await session.execute(select(Letter.id, Letter.number, Letter.subject).where(Letter.id.in_(reply_ids)))
        ).all()
    }
    tasks: list[SignatureTask] = []
    for document, signer in mine:
        if document.registration_requested_by is None or document.registration_requested_at is None:
            continue
        reply = replies.get(document.in_reply_to) if document.in_reply_to is not None else None
        tasks.append(
            SignatureTask(
                document_id=document.id,
                subject=document.subject,
                in_reply_to=None
                if reply is None
                else ReplyToLetter(id=reply.id, number=reply.number, subject=reply.subject),
                requested_by=directory.person(document.registration_requested_by),
                requested_at=document.registration_requested_at,
                acting_for=signer.acting_for[0] if signer.acting_for else None,
            )
        )
    return tasks


async def registrar_ids(session: AsyncSession) -> list[int]:
    """Активные держатели `letters.register` — делопроизводители, кому уходят задачи по ИСХ."""
    rows = await session.execute(
        select(Employee.crm_user_id)
        .where(Employee.is_active.is_(True), literal(P.LETTERS_REGISTER.value) == any_(Employee.permissions_eds))
        .order_by(Employee.crm_user_id)
    )
    return [int(uid) for uid in rows.scalars()]


async def _notice(
    session: AsyncSession,
    bus: AsyncBus,
    document: Document,
    *,
    key: str,
    recipients: Iterable[int | None],
    title: str,
    subtitle: str | None,
    actor_id: int | None,
    kind: str = "instruction_assigned",
    with_document: bool = True,
) -> None:
    """Уведомление по ответу на ВХ; ИСХ без ВХ (в событии `letter` обязателен) уведомлений не порождает."""
    if document.in_reply_to is None:
        return
    letter = await session.get(Letter, document.in_reply_to)
    if letter is None:
        return
    await instructions.notify(
        session,
        bus,
        letter=letter,
        kind=kind,
        key=key,
        recipients=recipients,
        title=title,
        subtitle=subtitle,
        actor_id=actor_id,
        document=document if with_document else None,
    )


async def _letter_number(session: AsyncSession, document: Document) -> str:
    row = await session.execute(select(Letter.number).where(Letter.id == document.in_reply_to))
    return row.scalar_one_or_none() or ""


async def notify_registered(
    session: AsyncSession, bus: AsyncBus, document: Document, *, closed_executors: list[int], actor_id: int
) -> None:
    """ИСХ зарегистрирован: исполнителю закрытого поручения и автору ответа (кроме того, кто зарегистрировал)."""
    number = await _letter_number(session, document)
    tail = "поручение исполнено" if closed_executors else document.subject
    await _notice(
        session,
        bus,
        document,
        key=f"document:{document.id}:registered",
        recipients=[uid for uid in (*closed_executors, document.author_crm_user_id) if uid != actor_id],
        title=f"Ответ зарегистрирован: {document.number}",
        subtitle=f"На {number} · {tail}"[:200],
        actor_id=actor_id,
        kind="letter_executed",
    )


async def notify_mail_failed(
    session: AsyncSession, bus: AsyncBus, document: Document, *, mailing_id: uuid.UUID, reason: str
) -> None:
    """Письмо не ушло адресату: автор и делопроизводители узнают сразу, повтор — «Отправить адресату ещё раз»."""
    await _notice(
        session,
        bus,
        document,
        key=f"document:{document.id}:mail:{mailing_id}:failed",
        recipients=[document.author_crm_user_id, *await registrar_ids(session)],
        title=f"Не отправлено: {document.number or document.subject}",
        subtitle=reason[:200],
        actor_id=None,
    )
