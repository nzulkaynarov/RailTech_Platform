"""Обращения сотрудников к администратору (W15-H7): создать, ответить, сменить статус.

Автор — любой сотрудник (видит только свои), админ видит все и отвечает. Ответ и решение уходят
автору в колокольчик Платформы (`staff_notifications`) и в Telegram, если привязан; новое
обращение — админам в колокольчик и личным сообщением бота. Уведомления — после коммита, отказ
Telegram обращение не откатывает.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import staff_tickets as rules
from app.domain.errors import (
    ConflictError,
    NotFoundError,
    RateLimitedError,
    Reason,
    ValidationFailedError,
)
from app.models.auth import Role, User, UserRole
from app.models.platform_roles import PlatformRole, UserPlatformRole
from app.models.staff_tickets import StaffTicket, StaffTicketMessage
from app.security import audit
from app.security.audit import Actor
from app.services import staff_notifications as notes

logger = structlog.get_logger(__name__)


class Messenger(Protocol):
    """Личные сообщения сотрудникам от бота (`StaffNotifier`): ошибка доставки не бросается."""

    async def direct(self, user_id: int, text: str, key: str) -> bool: ...

    async def alert_admins(self, text: str, key: str) -> int: ...


@dataclass(frozen=True, slots=True)
class TicketRow:
    id: int
    number: str
    subject: str
    status: str
    author_id: int
    author_name: str
    author_role: str | None
    page: str | None
    preview: str
    replies: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TicketMessageView:
    id: int
    author_id: int | None
    author_name: str | None
    body: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TicketDetail:
    row: TicketRow
    body: str
    messages: list[TicketMessageView]
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class TicketPage:
    items: list[TicketRow]
    total: int
    counts: dict[str, int]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def invalid(exc: rules.TicketValueError) -> ValidationFailedError:
    """Ошибка значения -> 422 с `details.field` и `details.reason`."""
    return ValidationFailedError(str(exc), reason=Reason(exc.reason), field=exc.field)


async def admin_user_ids(session: AsyncSession) -> list[int]:
    """Активные администраторы: роль CRM `admin` или роль Платформы с полным доступом к `admin`."""
    legacy = (
        select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.name == "admin")
    )
    platform = (
        select(UserPlatformRole.user_id)
        .join(PlatformRole, PlatformRole.id == UserPlatformRole.role_id)
        .where(PlatformRole.access["admin"].astext == "full")
    )
    stmt = (
        select(User.id)
        .where(User.is_active.is_(True), or_(User.id.in_(legacy), User.id.in_(platform)))
        .order_by(User.id)
    )
    return list((await session.scalars(stmt)).all())


class StaffTicketService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        messenger: Callable[[], Awaitable["Messenger | None"]],
        platform_url: str | None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sessions = sessions
        self._messenger = messenger
        self._platform_url = platform_url
        self._clock = clock

    # --- автор ---------------------------------------------------------------------------------

    async def create(
        self,
        actor: Actor,
        author_id: int,
        *,
        subject: str,
        body: str,
        page: str | None,
        role: str | None,
    ) -> TicketDetail:
        try:
            subject_ok = rules.checked_subject(subject)
            body_ok = rules.checked_body(body)
            page_ok = rules.checked_page(page)
        except rules.TicketValueError as exc:
            raise invalid(exc) from exc
        now = self._clock()
        async with self._sessions() as session, session.begin():
            # Автор блокируется на время проверки лимита: два параллельных запроса не обходят его.
            author = await session.get(User, author_id, with_for_update=True)
            if author is None or not author.is_active:
                raise NotFoundError("user not found")
            recent = await session.scalar(
                select(func.count())
                .select_from(StaffTicket)
                .where(
                    StaffTicket.author_id == author_id,
                    StaffTicket.created_at > rules.window_start(now),
                )
            )
            if rules.rate_exceeded(int(recent or 0)):
                raise RateLimitedError("too many requests", reason=Reason.TICKET_RATE_LIMITED)
            ticket = StaffTicket(
                author_id=author_id,
                subject=subject_ok,
                body=body_ok,
                page=page_ok,
                author_role=rules.clipped_role(role),
                status="new",
                created_at=now,
                updated_at=now,
            )
            session.add(ticket)
            await session.flush()
            number = rules.number_of(ticket.id)
            await audit.record(
                session, actor, "staff_ticket.create", "staff_ticket", ticket.id,
                after={"subject": subject_ok, "page": page_ok},
            )  # fmt: skip
            admins = [uid for uid in await admin_user_ids(session) if uid != author_id]
            notes.add_in(
                session,
                admins,
                kind="ticket_new",
                tab="system",
                title=f"Новое обращение {number}",
                subtitle=f"{author.full_name}: {rules.snippet(body_ok)}",
                object_kind="ticket",
                object_id=str(ticket.id),
                object_number=number,
            )
            ticket_id, author_name = ticket.id, author.full_name
        await self._alert_admins(number, author_name, body_ok, ticket_id)
        return await self.get(ticket_id)

    async def list_own(self, user_id: int) -> list[TicketRow]:
        stmt = self._rows_stmt().where(StaffTicket.author_id == user_id)
        async with self._sessions() as session:
            result = await session.execute(
                stmt.order_by(StaffTicket.created_at.desc(), StaffTicket.id.desc())
            )
            return [_row(*r) for r in result.all()]

    async def get_own(self, user_id: int, ticket_id: int) -> TicketDetail:
        detail = await self.get(ticket_id)
        if detail.row.author_id != user_id:
            raise NotFoundError("ticket not found")  # чужое обращение «не существует»
        return detail

    # --- админ ---------------------------------------------------------------------------------

    async def list_all(
        self,
        *,
        status: str | None,
        subject: str | None,
        limit: int,
        offset: int,
    ) -> TicketPage:
        try:
            if status is not None:
                rules.checked_status(status)
            if subject is not None:
                rules.checked_subject(subject)
        except rules.TicketValueError as exc:
            raise invalid(exc) from exc
        filters = []
        if status is not None:
            filters.append(StaffTicket.status == status)
        if subject is not None:
            filters.append(StaffTicket.subject == subject)
        stmt = self._rows_stmt().where(*filters)
        # Новое и «В работе» выше решённого, внутри — свежее выше.
        order = (
            func.array_position(["new", "in_progress", "resolved"], StaffTicket.status),
            StaffTicket.updated_at.desc(),
            StaffTicket.id.desc(),
        )
        async with self._sessions() as session:
            result = await session.execute(stmt.order_by(*order).limit(limit).offset(offset))
            items = [_row(*r) for r in result.all()]
            total = int(
                await session.scalar(select(func.count()).select_from(StaffTicket).where(*filters))
                or 0
            )
            counts = {
                name: int(count)
                for name, count in (
                    await session.execute(
                        select(StaffTicket.status, func.count()).group_by(StaffTicket.status)
                    )
                ).all()
            }
        return TicketPage(items, total, {s: counts.get(s, 0) for s in rules.STATUSES})

    async def count_new(self) -> int:
        async with self._sessions() as session:
            return int(
                await session.scalar(
                    select(func.count()).select_from(StaffTicket).where(StaffTicket.status == "new")
                )
                or 0
            )

    async def get(self, ticket_id: int) -> TicketDetail:
        async with self._sessions() as session:
            result = await session.execute(self._rows_stmt().where(StaffTicket.id == ticket_id))
            found = result.first()
            if found is None:
                raise NotFoundError("ticket not found")
            row = _row(*found)
            ticket = await session.get(StaffTicket, ticket_id)
            assert ticket is not None  # noqa: S101 — только что прочитан
            messages = (
                await session.execute(
                    select(StaffTicketMessage, User.full_name)
                    .outerjoin(User, User.id == StaffTicketMessage.author_id)
                    .where(StaffTicketMessage.ticket_id == ticket_id)
                    .order_by(StaffTicketMessage.created_at, StaffTicketMessage.id)
                )
            ).all()
            return TicketDetail(
                row=row,
                body=ticket.body,
                messages=[
                    TicketMessageView(m.id, m.author_id, name, m.body, m.created_at)
                    for m, name in messages
                ],
                resolved_at=ticket.resolved_at,
            )

    async def reply(
        self, actor: Actor, ticket_id: int, body: str, *, status: str | None = None
    ) -> TicketDetail:
        """Ответ админа автору; новое обращение берётся в работу, `status` задаёт итог сразу."""
        try:
            text = rules.checked_reply(body)
            target = rules.checked_status(status) if status is not None else None
        except rules.TicketValueError as exc:
            raise invalid(exc) from exc
        now = self._clock()
        async with self._sessions() as session, session.begin():
            ticket = await session.get(StaffTicket, ticket_id, with_for_update=True)
            if ticket is None:
                raise NotFoundError("ticket not found")
            before = ticket.status
            after = target or rules.after_reply(before)
            if after != before and not rules.can_move(before, after):
                raise ConflictError(
                    "status transition is not allowed", reason=Reason.TICKET_STATUS_TRANSITION
                )
            session.add(
                StaffTicketMessage(
                    ticket_id=ticket_id, author_id=actor.user_id, body=text, created_at=now
                )
            )
            self._apply_status(ticket, after, now)
            await audit.record(
                session, actor, "staff_ticket.reply", "staff_ticket", ticket_id,
                before={"status": before}, after={"status": after},
            )  # fmt: skip
            number = rules.number_of(ticket_id)
            author = await session.get(User, ticket.author_id)
            language = author.language if author else None
            note = rules.reply_note(language, number, text)
            notes.add_in(
                session,
                [ticket.author_id],
                kind="ticket_reply",
                tab="system",
                title=note.title,
                subtitle=note.subtitle,
                object_kind="ticket",
                object_id=str(ticket_id),
                object_number=number,
            )
            author_id = ticket.author_id
        await self._tell_author(author_id, language, number, text, ticket_id)
        return await self.get(ticket_id)

    async def set_status(self, actor: Actor, ticket_id: int, status: str) -> TicketDetail:
        try:
            target = rules.checked_status(status)
        except rules.TicketValueError as exc:
            raise invalid(exc) from exc
        now = self._clock()
        async with self._sessions() as session, session.begin():
            ticket = await session.get(StaffTicket, ticket_id, with_for_update=True)
            if ticket is None:
                raise NotFoundError("ticket not found")
            before = ticket.status
            if not rules.can_move(before, target):
                raise ConflictError(
                    "status transition is not allowed", reason=Reason.TICKET_STATUS_TRANSITION
                )
            self._apply_status(ticket, target, now)
            await audit.record(
                session, actor, "staff_ticket.status", "staff_ticket", ticket_id,
                before={"status": before}, after={"status": target},
            )  # fmt: skip
            number = rules.number_of(ticket_id)
            author = await session.get(User, ticket.author_id)
            language = author.language if author else None
            if target == "resolved":
                note = rules.resolved_note(language, number, ticket.body)
                notes.add_in(
                    session,
                    [ticket.author_id],
                    kind="ticket_resolved",
                    tab="system",
                    title=note.title,
                    subtitle=note.subtitle,
                    object_kind="ticket",
                    object_id=str(ticket_id),
                    object_number=number,
                )
        return await self.get(ticket_id)

    # --- внутреннее -----------------------------------------------------------------------------

    @staticmethod
    def _apply_status(ticket: StaffTicket, status: str, now: datetime) -> None:
        if status == ticket.status:
            ticket.updated_at = now
            return
        ticket.status = status
        ticket.updated_at = now
        ticket.resolved_at = now if status == "resolved" else None

    @staticmethod
    def _rows_stmt() -> Select[Any]:
        replies = (
            select(func.count(StaffTicketMessage.id))
            .where(StaffTicketMessage.ticket_id == StaffTicket.id)
            .correlate(StaffTicket)
            .scalar_subquery()
        )
        return select(
            StaffTicket.id,
            StaffTicket.subject,
            StaffTicket.status,
            StaffTicket.author_id,
            User.full_name,
            StaffTicket.author_role,
            StaffTicket.page,
            StaffTicket.body,
            replies,
            StaffTicket.created_at,
            StaffTicket.updated_at,
        ).join(User, User.id == StaffTicket.author_id)

    async def _alert_admins(self, number: str, author: str, body: str, ticket_id: int) -> None:
        messenger = await self._messenger()
        if messenger is None:
            return
        link = self._link(f"/admin/tickets/{number}")
        text = f"Новое обращение {number} от {author}: {rules.snippet(body, 200)}"
        text = f"{text}\n{link}" if link else text
        try:
            await messenger.alert_admins(text, f"staff_ticket:{ticket_id}")
        except Exception:
            logger.exception("staff_ticket_alert_failed", ticket_id=ticket_id)

    async def _tell_author(
        self, author_id: int, language: str | None, number: str, text: str, ticket_id: int
    ) -> None:
        messenger = await self._messenger()
        if messenger is None:
            return
        link = self._link(f"/help/requests/{number}") or ""
        try:
            await messenger.direct(
                author_id,
                rules.telegram_text(language, number, text, link),
                f"staff_ticket_reply:{ticket_id}",
            )
        except Exception:
            logger.exception("staff_ticket_reply_dm_failed", ticket_id=ticket_id)

    def _link(self, path: str) -> str | None:
        return f"{self._platform_url.rstrip('/')}{path}" if self._platform_url else None


def _row(
    ticket_id: int,
    subject: str,
    status: str,
    author_id: int,
    author_name: str,
    author_role: str | None,
    page: str | None,
    body: str,
    replies: int,
    created_at: datetime,
    updated_at: datetime,
) -> TicketRow:
    return TicketRow(
        id=ticket_id,
        number=rules.number_of(ticket_id),
        subject=subject,
        status=status,
        author_id=author_id,
        author_name=author_name,
        author_role=author_role,
        page=page,
        preview=rules.snippet(body, 140),
        replies=int(replies or 0),
        created_at=created_at,
        updated_at=updated_at,
    )


__all__: Sequence[str] = (
    "StaffTicketService",
    "TicketDetail",
    "TicketPage",
    "TicketRow",
    "admin_user_ids",
)
