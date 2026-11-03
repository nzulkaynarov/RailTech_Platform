"""Представления очереди «Входящая почта» (W18A-P2-3): вкладки, счётчики, поиск, «прочитано».

Все запросы — по записям (корням цепочек, `thread_root_id IS NULL`). Первая линия (`full`) видит
всё;
остальной сотрудник — только письма, где он исполнитель или названный в «лично адресованном»
(`Scope`). «Мои задачи» (`tasks`) — новые не из истории и мои «в работе»: решает CRM, не BFF.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, and_, case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuditLog, User
from app.models.inbound_mail import InboundMail, InboundMailRead

View = Literal["new", "mine", "in_work", "done", "spam", "all", "tasks"]
ACTIVE = ("in_work", "registering")


@dataclass(frozen=True, slots=True)
class Scope:
    user_id: int
    full: bool


def _mine(scope: Scope) -> ColumnElement[bool]:
    return and_(InboundMail.status.in_(ACTIVE), InboundMail.assignee_id == scope.user_id)


def _named(scope: Scope) -> ColumnElement[bool]:
    """Письмо «лично», где сотрудник назван (соадресат или «для сведения»)."""
    uid = scope.user_id
    return and_(
        InboundMail.personal.is_(True),
        or_(InboundMail.to_staff_ids.contains([uid]), InboundMail.cc_staff_ids.contains([uid])),
    )


def scope_clause(scope: Scope) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = [InboundMail.thread_root_id.is_(None)]
    if not scope.full:
        where.append(
            or_(InboundMail.assignee_id == scope.user_id, _named(scope)),
        )
        where.append(InboundMail.status != "spam")
    return where


def view_clause(view: View, scope: Scope, history: bool | None = None) -> list[ColumnElement[bool]]:
    where = scope_clause(scope)
    if view == "new":
        where.append(InboundMail.status == "new")
        if history is not None:
            where.append(InboundMail.from_history.is_(history))
    elif view == "mine":
        where.append(_mine(scope))
    elif view == "in_work":
        where.append(InboundMail.status.in_(ACTIVE))
    elif view in ("done", "spam"):
        where.append(InboundMail.status == view)
    elif view == "all":
        where.append(InboundMail.status != "spam")
    else:  # tasks
        fresh = and_(InboundMail.status == "new", InboundMail.from_history.is_(False))
        where.append(or_(fresh, _mine(scope)) if scope.full else _mine(scope))
    return where


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _search(q: str | None) -> list[ColumnElement[bool]]:
    text = (q or "").strip()[:100]
    if not text:
        return []
    pattern = _like(text)
    return [
        or_(
            InboundMail.from_email.ilike(pattern, escape="\\"),
            InboundMail.from_name.ilike(pattern, escape="\\"),
            InboundMail.subject.ilike(pattern, escape="\\"),
        )
    ]


def unread_expr(scope: Scope) -> Any:
    """Письмо не прочитано этим сотрудником: отметки нет или она старше последнего входящего."""
    return or_(InboundMailRead.read_at.is_(None), InboundMailRead.read_at < InboundMail.activity_at)


def _with_read(scope: Scope) -> Any:
    return and_(InboundMailRead.mail_id == InboundMail.id, InboundMailRead.user_id == scope.user_id)


async def page(
    session: AsyncSession,
    view: View,
    scope: Scope,
    *,
    limit: int,
    history: bool | None = None,
    q: str | None = None,
) -> list[tuple[InboundMail, bool]]:
    """Записи вкладки (новые сверху по последнему входящему) с признаком «не прочитано»."""
    stmt = (
        select(InboundMail, unread_expr(scope))
        .outerjoin(InboundMailRead, _with_read(scope))
        .where(*view_clause(view, scope, history), *_search(q))
        .order_by(InboundMail.activity_at.desc(), InboundMail.id.desc())
        .limit(limit)
    )
    return [(row, bool(unread)) for row, unread in (await session.execute(stmt)).all()]


async def total(
    session: AsyncSession,
    view: View,
    scope: Scope,
    *,
    history: bool | None = None,
    q: str | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(InboundMail)
        .where(*view_clause(view, scope, history), *_search(q))
    )
    return int((await session.execute(stmt)).scalar_one())


async def counts(session: AsyncSession, scope: Scope) -> dict[str, int]:
    """Числа вкладок одним запросом (без поиска): в рамках прав сотрудника."""
    keys: dict[str, ColumnElement[bool]] = {
        "new": and_(*view_clause("new", scope)),
        "history": and_(*view_clause("new", scope, True)),
        "mine": and_(*view_clause("mine", scope)),
        "in_work": and_(*view_clause("in_work", scope)),
        "done": and_(*view_clause("done", scope)),
        "spam": and_(*view_clause("spam", scope)),
        "all": and_(*view_clause("all", scope)),
    }
    cols = [func.count().filter(cond).label(key) for key, cond in keys.items()]
    row = (await session.execute(select(*cols).select_from(InboundMail))).one()
    return {key: int(getattr(row, key)) for key in keys}


async def unread_new(session: AsyncSession, scope: Scope) -> int:
    stmt = (
        select(func.count())
        .select_from(InboundMail)
        .outerjoin(InboundMailRead, _with_read(scope))
        .where(*view_clause("new", scope), unread_expr(scope))
    )
    return int((await session.execute(stmt)).scalar_one())


async def is_unread(session: AsyncSession, row: InboundMail, user_id: int) -> bool:
    stmt = select(InboundMailRead.read_at).where(
        InboundMailRead.mail_id == row.id, InboundMailRead.user_id == user_id
    )
    read_at = (await session.execute(stmt)).scalar_one_or_none()
    return read_at is None or read_at < row.activity_at


async def mark_read(session: AsyncSession, mail_id: int, user_id: int, now: datetime) -> None:
    from sqlalchemy.dialects.postgresql import insert

    stmt = insert(InboundMailRead).values(mail_id=mail_id, user_id=user_id, read_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=[InboundMailRead.mail_id, InboundMailRead.user_id],
        set_={"read_at": now},
    )
    await session.execute(stmt)


async def message_counts(session: AsyncSession, root_ids: Sequence[int]) -> dict[int, int]:
    """Сколько входящих писем в записи (корень + ответы цепочки)."""
    if not root_ids:
        return {}
    stmt = (
        select(
            func.coalesce(InboundMail.thread_root_id, InboundMail.id).label("root"),
            func.count(),
        )
        .where(func.coalesce(InboundMail.thread_root_id, InboundMail.id).in_(list(root_ids)))
        .group_by("root")
    )
    return {int(r): int(n) for r, n in (await session.execute(stmt)).all()}


async def user_names(session: AsyncSession, ids: Sequence[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(list(ids))))
    return {int(i): str(n) for i, n in rows.all()}


async def staff_by_email(session: AsyncSession, emails: Sequence[str]) -> dict[str, int]:
    """Активные сотрудники CRM по адресу (нижний регистр) — «Кому» и копия письма."""
    wanted = [e.lower() for e in emails if e]
    if not wanted:
        return {}
    stmt = select(func.lower(User.email), User.id).where(
        func.lower(User.email).in_(wanted), User.is_active.is_(True)
    )
    return {str(e): int(i) for e, i in (await session.execute(stmt)).all()}


async def children(session: AsyncSession, root_id: int) -> Sequence[InboundMail]:
    stmt = (
        select(InboundMail)
        .where(InboundMail.thread_root_id == root_id)
        .order_by(InboundMail.received_at, InboundMail.id)
    )
    return (await session.scalars(stmt)).all()


async def thread_root(
    session: AsyncSession, message_ids: Sequence[str], *, for_update: bool = False
) -> InboundMail | None:
    """Запись (корень), к которой относится письмо с этими `In-Reply-To`/`References`: ближайшее
    известное письмо цепочки — сам корень или ответ в нём."""
    if not message_ids:
        return None
    ids = list(message_ids)
    rank = case({m: i for i, m in enumerate(ids)}, value=InboundMail.message_id, else_=literal(99))
    found = (
        await session.execute(
            select(InboundMail.id, InboundMail.thread_root_id)
            .where(InboundMail.message_id.in_(ids))
            .order_by(rank)
            .limit(1)
        )
    ).first()
    if found is None:
        return None
    root_id = int(found[1] if found[1] is not None else found[0])
    stmt = select(InboundMail).where(InboundMail.id == root_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


async def latest_incoming(session: AsyncSession, root_id: int) -> InboundMail | None:
    """Последнее входящее письмо записи — на него идёт ответ."""
    stmt = (
        select(InboundMail)
        .where(or_(InboundMail.id == root_id, InboundMail.thread_root_id == root_id))
        .order_by(InboundMail.received_at.desc(), InboundMail.id.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def journal(session: AsyncSession, mail_id: int, limit: int = 100) -> Sequence[AuditLog]:
    """Что делали с письмом (аудит CRM): кто, что и когда; текстов писем в журнале нет."""
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.entity_type == "inbound_mail",
            AuditLog.entity_id == str(mail_id),
            AuditLog.action.like("inbound\\_mail.%"),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()
    return list(reversed(rows))


async def chain_messages(
    session: AsyncSession, root_id: int
) -> list[tuple[str, list[str], list[str]]]:
    """Отправитель, «Кому» и копия каждого входящего письма записи — для адресов цепочки."""
    stmt = (
        select(InboundMail.from_email, InboundMail.to_addrs, InboundMail.cc_addrs)
        .where(or_(InboundMail.id == root_id, InboundMail.thread_root_id == root_id))
        .order_by(InboundMail.received_at, InboundMail.id)
    )
    return [(f, list(t or []), list(c or [])) for f, t, c in (await session.execute(stmt)).all()]
