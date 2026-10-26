"""Реестр «Все документы» (SPEC-v3 §7.3; eds.yaml `GET /registry`): письма, КП, служебные, заявления, отчёты.

Один запрос объединяет письма (`letters`), документы (`documents`) и маршруты КП (`approval_routes`, template = quote)
в общий вид и фильтрует его: вкладка (тип), статус, период (по `Asia/Tashkent`), ответственный, клиент, номер, поиск
по номеру и теме. Доступ — `registry.read`; видны все строки (сужение «свои» — у `/documents` и `/approvals`).
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import (
    BigInteger,
    CompoundSelect,
    Date,
    Select,
    String,
    cast,
    func,
    literal_column,
    null,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import COMPANY_TZ
from app.models import ApprovalRoute, ApprovalStep, Document, Letter
from app.schemas.common import ErpLinks, LetterSender
from app.schemas.pagination import decode_cursor
from app.schemas.registry import RegistryItem, RegistryKind, RegistryPage
from app.services import paging
from app.services.letters_read import escape_like
from app.services.people import Directory, load_directory

EXPORT_LIMIT = 10_000


@dataclass(frozen=True)
class Filters:
    kinds: list[RegistryKind] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    responsible: int | None = None
    crm_client_id: int | None = None
    number: str | None = None
    q: str | None = None


def _big(value: Any = None) -> Any:
    return cast(null() if value is None else value, BigInteger)


def _union() -> CompoundSelect[Any]:
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
    )
    documents = select(
        cast(literal_column("documents.kind"), String).label("kind"),
        Document.id,
        Document.number,
        Document.subject,
        Document.status,
        Document.created_at,
        Document.author_crm_user_id,
        Document.recipient_name,
        Document.recipient_inn,
        _big(),
        Document.erp_deal_id,
        Document.deal_number,
        _big(),
        _big(),
    )
    quotes = select(
        cast(literal_column("'quote'"), String).label("kind"),
        ApprovalRoute.id,
        ApprovalRoute.quote_number,
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
    ).where(ApprovalRoute.template == "quote")
    return union_all(letters, documents, quotes)


def _filtered(filters: Filters) -> Select[Any]:
    rows = _union().subquery("registry")
    c = rows.c
    stmt = select(rows)
    if filters.kinds:
        stmt = stmt.where(c.kind.in_([k.value for k in filters.kinds]))
    if filters.statuses:
        stmt = stmt.where(c.status.in_(filters.statuses))
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
        stmt = stmt.where(c.number == filters.number)
    if filters.q and filters.q.strip():
        like = f"%{escape_like(filters.q.strip())}%"
        stmt = stmt.where(c.number.ilike(like, escape="\\") | c.title.ilike(like, escape="\\"))
    return stmt


def _item(row: Any, directory: Directory) -> RegistryItem:
    named = row.client_name is not None or row.client_inn is not None
    return RegistryItem(
        kind=RegistryKind(row.kind),
        id=row.id,
        number=row.number,
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
    )


async def list_page(session: AsyncSession, filters: Filters, *, cursor: str | None, limit: int) -> RegistryPage:
    sub = _filtered(filters).subquery("page")
    stmt = paging.apply(select(sub), sub.c.registered_at, sub.c.id, decode_cursor(cursor), limit)
    rows = list((await session.execute(stmt)).all())
    page, next_cursor = paging.cut(rows, limit, lambda r: r.registered_at, lambda r: r.id)
    directory = await load_directory(session, (r.responsible for r in page))
    return RegistryPage(items=[_item(r, directory) for r in page], next_cursor=next_cursor)


async def export_rows(session: AsyncSession, filters: Filters) -> list[RegistryItem] | None:
    """Все строки по фильтрам, новые первыми; `None` — больше `EXPORT_LIMIT` (экспорт отклоняется)."""
    sub = _filtered(filters).subquery("export")
    stmt = select(sub).order_by(sub.c.registered_at.desc(), sub.c.id.desc()).limit(EXPORT_LIMIT + 1)
    rows = list((await session.execute(stmt)).all())
    if len(rows) > EXPORT_LIMIT:
        return None
    directory = await load_directory(session, (r.responsible for r in rows))
    return [_item(r, directory) for r in rows]
