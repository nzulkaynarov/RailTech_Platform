"""Замещение на время отсутствия (W15-H6): заместитель видит очередь замещаемого в период.

Данные — в `users.deputy_user_id/deputy_from/deputy_to` (одно замещение на сотрудника). Права
заместителя не расширяются: `GET /inbox?on_behalf_of=<id>` отдаёт его очередь только если сегодня
(по календарю замещаемого) период активен и заместитель — тот, кто назначен; объекты потом
открываются по правам самого заместителя.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import staff_profile as rules
from app.domain.errors import ForbiddenError, NotFoundError, Reason, ValidationFailedError
from app.domain.lead_access import WORK_ROLES
from app.models.auth import Role, User, UserRole
from app.repositories import users as repo
from app.security import audit
from app.security.audit import Actor
from app.services.staff_profile import invalid


@dataclass(frozen=True, slots=True)
class Candidate:
    id: int
    full_name: str
    position: str | None


@dataclass(frozen=True, slots=True)
class Covered:
    user_id: int
    full_name: str
    date_from: date
    date_to: date


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StaffDeputyService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sessions = sessions
        self._clock = clock

    async def candidates(self, user_id: int) -> list[Candidate]:
        """Коллеги, которые могут вести очередь: активные, с рабочей ролью CRM, не сам сотрудник."""
        stmt = (
            select(User.id, User.full_name, User.position)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.is_active.is_(True), User.id != user_id, Role.name.in_(WORK_ROLES))
            .distinct()
            .order_by(User.full_name, User.id)
        )
        async with self._sessions() as session:
            return [Candidate(*row) for row in (await session.execute(stmt)).all()]

    async def set(
        self, actor: Actor, user_id: int, deputy_user_id: int, date_from: date, date_to: date
    ) -> None:
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            today = rules.local_today(user.timezone, self._clock())
            try:
                period = rules.checked_deputy(user_id, deputy_user_id, date_from, date_to, today)
            except rules.ProfileValueError as exc:
                raise invalid(exc) from exc
            deputy = await repo.get(session, deputy_user_id)
            roles = set(await repo.roles_of(session, deputy_user_id)) if deputy else set()
            if deputy is None or not deputy.is_active or not roles & WORK_ROLES:
                raise ValidationFailedError(
                    "the deputy cannot work the queue",
                    reason=Reason.DEPUTY_NOT_COLLEAGUE,
                    field="deputy_user_id",
                )
            before = _audit_of(user)
            user.deputy_user_id = period.deputy_user_id
            user.deputy_from = period.date_from
            user.deputy_to = period.date_to
            await audit.record(
                session, actor, "user.deputy_set", "user", user_id,
                before=before, after=_audit_of(user),
            )  # fmt: skip

    async def clear(self, actor: Actor, user_id: int) -> None:
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            if user.deputy_from is not None:
                before = _audit_of(user)
                user.deputy_user_id = user.deputy_from = user.deputy_to = None
                await audit.record(
                    session, actor, "user.deputy_cleared", "user", user_id, before=before
                )

    async def deputy_name(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
        return user.full_name if user else None

    async def covering(self, deputy_user_id: int) -> list[Covered]:
        """За кого этот сотрудник сегодня заместитель (период активен по календарю замещаемого)."""
        stmt = (
            select(User)
            .where(User.deputy_user_id == deputy_user_id, User.is_active.is_(True))
            .order_by(User.full_name, User.id)
        )
        now = self._clock()
        async with self._sessions() as session:
            users = (await session.scalars(stmt)).all()
        covered: list[Covered] = []
        for u in users:
            if u.deputy_from is None or u.deputy_to is None:
                continue
            period = rules.DeputyPeriod(deputy_user_id, u.deputy_from, u.deputy_to)
            if period.active_on(rules.local_today(u.timezone, now)):
                covered.append(Covered(u.id, u.full_name, u.deputy_from, u.deputy_to))
        return covered

    async def require_covering(self, deputy_user_id: int, covered_user_id: int) -> Covered:
        for item in await self.covering(deputy_user_id):
            if item.user_id == covered_user_id:
                return item
        raise ForbiddenError("you are not covering this colleague now", reason=Reason.NOT_A_DEPUTY)


def _audit_of(user: User) -> dict[str, object]:
    return {
        "deputy_user_id": user.deputy_user_id,
        "deputy_from": user.deputy_from.isoformat() if user.deputy_from else None,
        "deputy_to": user.deputy_to.isoformat() if user.deputy_to else None,
    }
