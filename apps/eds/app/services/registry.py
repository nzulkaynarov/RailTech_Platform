"""Реестр «Все документы» (SPEC-v3 §7.3; eds.yaml `GET /registry`): письма, КП, служебные, заявления, отчёты и
договоры, счета, акты проектов.

Один запрос объединяет письма (`letters`), документы (`documents`), маршруты КП (`approval_routes`, template = quote) и
документы проектов из ERP (`project_documents`, D2-5: договор, счёт, акт) в общий вид и фильтрует его: вкладка (тип),
статус, период (по `Asia/Tashkent`), ответственный, клиент, номер, поиск по номеру и теме. Доступ — `registry.read`, но
реестр **не шире прав на сам вид документа** (D1-10): письма (`letter_in`, `letter_out`) — только с `letters.read`;
черновики (`status = draft`) — только автору; документы — по `access.document_visible` (он же у `/documents`, карточки
и файлов), КП — по `access.route_visible`; договоры, счета и акты проектов — с `registry.read`.
Отбор — в SQL до курсора и счётчиков.
"""

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    CompoundSelect,
    Date,
    Numeric,
    Select,
    String,
    and_,
    cast,
    false,
    func,
    literal_column,
    not_,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.clock import COMPANY_TZ
from app.models import ApprovalRoute, ApprovalStep, Document, Employee, Letter, ProjectDocument
from app.schemas.common import ErpLinks, LetterSender, Money, PersonRef
from app.schemas.pagination import decode_cursor
from app.schemas.registry import RegistryItem, RegistryKind, RegistryPage, RegistryStage
from app.services import access, delivery, paging, signing_resolve, signing_state
from app.services.letters_read import escape_like
from app.services.people import Directory, load_directory

EXPORT_LIMIT = 10_000

#: Конечные статусы по виду (eds.yaml 0.15.0, `RegistryStage`): документ больше не ждёт ничьего действия — «Архив».
#: Остальные — «открыт»: ждёт сотрудника или контрагента (одобренное КП ждёт клиента, выставленный счёт — оплаты).
DONE_STATUSES: dict[str, tuple[str, ...]] = {
    "letter_in": ("executed", "noted", "duplicate", "closed", "rejected"),
    "letter_out": ("approved", "rejected", "paid", "sent"),
    "memo": ("approved", "rejected", "paid", "sent"),
    "application": ("approved", "rejected", "paid", "sent"),
    "report": ("approved", "rejected", "paid", "sent"),
    "quote": ("rejected",),
    "contract": ("signed", "rejected"),
    "invoice": ("paid",),
    "act": ("signed",),
}


@dataclass(frozen=True)
class Filters:
    kinds: list[RegistryKind] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    stage: RegistryStage | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    responsible: int | None = None
    crm_client_id: int | None = None
    number: str | None = None
    q: str | None = None


def _text_null() -> Any:
    return cast(null(), String)


def _big(value: Any = None) -> Any:
    return cast(null() if value is None else value, BigInteger)


def _union(employee: Employee) -> CompoundSelect[Any]:
    current_assignee = (
        select(ApprovalStep.assignee_crm_user_id)
        .where(ApprovalStep.approval_id == ApprovalRoute.id, ApprovalStep.index == ApprovalRoute.current_step)
        .scalar_subquery()
    )
    last_decider = (
        select(ApprovalStep.decided_by)
        .where(ApprovalStep.approval_id == ApprovalRoute.id, ApprovalStep.decided_by.is_not(None))
        .order_by(ApprovalStep.index.desc())
        .limit(1)
        .scalar_subquery()
    )
    letters = select(
        cast(literal_column("'letter_in'"), String).label("kind"),
        Letter.id.label("id"),
        Letter.number.label("number"),
        Letter.previous_number.label("previous_number"),
        Letter.subject.label("title"),
        Letter.status.label("status"),
        Letter.registered_at.label("registered_at"),
        Letter.manager_crm_user_id.label("responsible"),
        Letter.sender_name.label("client_name"),
        Letter.sender_inn.label("client_inn"),
        Letter.erp_request_id.label("erp_request_id"),
        Letter.erp_deal_id.label("erp_deal_id"),
        Letter.deal_number.label("deal_number"),
        Letter.crm_client_id.label("crm_client_id"),
        Letter.erp_company_id.label("erp_company_id"),
        cast(null(), Numeric).label("amount"),
        cast(null(), String).label("currency"),
        false().label("undelivered"),
        false().label("awaiting_signature"),
    )
    documents = select(
        cast(literal_column("documents.kind"), String).label("kind"),
        Document.id.label("id"),
        Document.number.label("number"),
        Document.previous_number.label("previous_number"),
        Document.subject.label("title"),
        Document.status.label("status"),
        Document.created_at.label("registered_at"),
        Document.author_crm_user_id.label("responsible"),
        Document.recipient_name.label("client_name"),
        Document.recipient_inn.label("client_inn"),
        _big().label("erp_request_id"),
        Document.erp_deal_id.label("erp_deal_id"),
        Document.deal_number.label("deal_number"),
        _big().label("crm_client_id"),
        _big().label("erp_company_id"),
        cast(Document.amount, Numeric).label("amount"),
        Document.currency.label("currency"),
        # СЦ-1: письмо с почтой адресата, которое не ушло, — не «Архив», а «Исходящие»
        delivery.undelivered().label("undelivered"),
        signing_state.awaiting_signature().label("awaiting_signature"),
    ).where(access.document_visible(employee))  # письма и чужие черновики отсекает сам предикат видимости
    quotes = select(
        cast(literal_column("'quote'"), String).label("kind"),
        ApprovalRoute.id,
        ApprovalRoute.quote_number,
        _text_null(),
        ApprovalRoute.title,
        ApprovalRoute.status,
        ApprovalRoute.created_at,
        func.coalesce(current_assignee, last_decider),
        ApprovalRoute.quote_snapshot["client_name"].astext,
        cast(null(), String),
        _big(),
        ApprovalRoute.erp_deal_id,
        ApprovalRoute.deal_number,
        ApprovalRoute.crm_client_id,
        ApprovalRoute.erp_company_id,
        cast(ApprovalRoute.quote_snapshot["total"].astext, Numeric),
        ApprovalRoute.quote_snapshot["currency"].astext,
        false(),
        false(),
    ).where(ApprovalRoute.template == "quote", access.route_visible(employee))
    parts = [documents, quotes]
    # Входящие письма — метаданные отправителя (имя, ИНН) — только с `letters.read`, как `/letters`.
    if access.can_read_letters(employee):
        parts.insert(0, letters)
    # Договоры, счета и акты проектов (D2-5) — суммы и клиенты проекта: только с `registry.read`.
    if access.can_read_project_documents(employee):
        parts.append(_project_documents())
    return union_all(*parts)


def _project_documents() -> Select[Any]:
    return select(
        cast(ProjectDocument.kind, String),
        ProjectDocument.id,
        ProjectDocument.number,
        _text_null(),
        ProjectDocument.title,
        ProjectDocument.status,
        ProjectDocument.registered_at,
        ProjectDocument.responsible_crm_user_id,
        ProjectDocument.client_name,
        ProjectDocument.client_inn,
        _big(),
        ProjectDocument.erp_deal_id,
        ProjectDocument.deal_number,
        ProjectDocument.crm_client_id,
        ProjectDocument.erp_company_id,
        cast(ProjectDocument.amount, Numeric),
        ProjectDocument.currency,
        false(),
        false(),
    )


def _done(kind: Any, status: Any) -> ColumnElement[bool]:
    return or_(*(and_(kind == k, status.in_(statuses)) for k, statuses in DONE_STATUSES.items()))


def _filtered(employee: Employee, filters: Filters) -> Select[Any]:
    rows = _union(employee).subquery("registry")
    c = rows.c
    stmt = select(rows)
    if filters.kinds:
        stmt = stmt.where(c.kind.in_([k.value for k in filters.kinds]))
    if filters.statuses:
        stmt = stmt.where(c.status.in_(filters.statuses))
    if filters.stage is not None:
        # Конечный статус — ещё не исход: недоставленное письмо остаётся открытым (`ui-standard.md` §14 п. 1)
        done = and_(_done(c.kind, c.status), not_(c.undelivered))
        stmt = stmt.where(done if filters.stage == RegistryStage.DONE else not_(done))
    local_day = cast(func.timezone(COMPANY_TZ.key, c.registered_at), Date)
    if filters.date_from:
        stmt = stmt.where(local_day >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(local_day <= filters.date_to)
    if filters.responsible is not None:
        stmt = stmt.where(c.responsible == filters.responsible)
    if filters.crm_client_id is not None:
        stmt = stmt.where(c.crm_client_id == filters.crm_client_id)
    if filters.number:
        stmt = stmt.where((c.number == filters.number) | (c.previous_number == filters.number))
    if filters.q and filters.q.strip():
        like = f"%{escape_like(filters.q.strip())}%"
        stmt = stmt.where(
            c.number.ilike(like, escape="\\")
            | c.previous_number.ilike(like, escape="\\")
            | c.title.ilike(like, escape="\\")
        )
    return stmt


def _item(row: Any, directory: Directory, signers: dict[uuid.UUID, PersonRef] | None = None) -> RegistryItem:
    named = row.client_name is not None or row.client_inn is not None
    return RegistryItem(
        kind=RegistryKind(row.kind),
        id=row.id,
        number=row.number,
        previous_number=row.previous_number,
        title=row.title,
        status=row.status,
        registered_at=row.registered_at,
        responsible=directory.person_or_none(row.responsible),
        client=LetterSender(name=row.client_name, inn=row.client_inn) if named else None,
        links=ErpLinks(
            erp_request_id=row.erp_request_id,
            erp_deal_id=row.erp_deal_id,
            deal_number=row.deal_number,
            crm_client_id=row.crm_client_id,
            erp_company_id=row.erp_company_id,
        ),
        amount=(
            Money(amount=f"{row.amount:.2f}", currency=row.currency)
            if row.amount is not None and row.currency
            else None
        ),
        undelivered=bool(row.undelivered),
        awaiting_signature=bool(row.awaiting_signature),
        signer=(signers or {}).get(row.id),
    )


async def _signers(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, PersonRef]:
    """«На подписи у …» (ГЛ-0): подписант писем страницы — то же правило, что у очереди."""
    if not ids:
        return {}
    documents = list((await session.execute(select(Document).where(Document.id.in_(ids)))).scalars())
    picked = await signing_resolve.letter_signers(session, documents, clock.company_date(clock.now()))
    return {doc_id: c.signer for doc_id, c in picked.items() if c is not None}


async def list_page(
    session: AsyncSession,
    employee: Employee,
    filters: Filters,
    *,
    cursor: str | None,
    limit: int,
    sort: str | None = None,
) -> RegistryPage:
    sub = _filtered(employee, filters).subquery("page")
    ordering = paging.parse_sort(sort)
    if ordering is None:
        stmt = paging.apply(select(sub), sub.c.registered_at, sub.c.id, decode_cursor(cursor), limit)
        rows = list((await session.execute(stmt)).all())
        page, next_cursor = paging.cut(rows, limit, lambda r: r.registered_at, lambda r: r.id)
    else:
        column = {
            "number": sub.c.number,
            "subject": sub.c.title,
            "status": sub.c.status,
            "amount": sub.c.amount,
            "created": sub.c.registered_at,
        }[ordering[0]]
        stmt = paging.apply_sorted(select(sub), column, sub.c.id, ordering, cursor, limit)
        rows = list((await session.execute(stmt)).all())
        attr = {
            "number": "number",
            "subject": "title",
            "status": "status",
            "amount": "amount",
            "created": "registered_at",
        }
        page, next_cursor = paging.cut_sorted(
            rows, limit, ordering, lambda r: getattr(r, attr[ordering[0]]), lambda r: r.id
        )
    directory = await load_directory(session, (r.responsible for r in page))
    signers = await _signers(session, [r.id for r in page if r.awaiting_signature])
    return RegistryPage(items=[_item(r, directory, signers) for r in page], next_cursor=next_cursor)


async def export_rows(session: AsyncSession, employee: Employee, filters: Filters) -> list[RegistryItem] | None:
    """Все строки по фильтрам, новые первыми; `None` — больше `EXPORT_LIMIT` (экспорт отклоняется)."""
    sub = _filtered(employee, filters).subquery("export")
    stmt = select(sub).order_by(sub.c.registered_at.desc(), sub.c.id.desc()).limit(EXPORT_LIMIT + 1)
    rows = list((await session.execute(stmt)).all())
    if len(rows) > EXPORT_LIMIT:
        return None
    directory = await load_directory(session, (r.responsible for r in rows))
    return [_item(r, directory) for r in rows]
