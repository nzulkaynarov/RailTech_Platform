"""Уведомления сотрудникам от CRM для колокольчика Платформы (W15-H7, platform-bff.md §4).

Общий механизм «событие CRM → колокольчик»: сервис пишет строку в `staff_notifications` (в той же
транзакции, что и событие), BFF сливает её с лентой ERP. Первые события — ответ админа на
обращение, решение обращения, новое обращение админам, привязка Telegram. Читать и отмечать
прочитанным можно только свои уведомления.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import NotFoundError
from app.models.staff_tickets import StaffNotification

# Платформа показывает ленту целиком по 200 новейшим (как ERP): старше уходит из колокольчика.
LIST_LIMIT = 200


@dataclass(frozen=True, slots=True)
class NotificationView:
    id: int
    kind: str
    tab: str
    title: str
    subtitle: str | None
    object_kind: str | None
    object_id: str | None
    object_number: str | None
    created_at: datetime
    read: bool


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _view(row: StaffNotification) -> NotificationView:
    return NotificationView(
        id=row.id,
        kind=row.kind,
        tab=row.tab,
        title=row.title,
        subtitle=row.subtitle,
        object_kind=row.object_kind,
        object_id=row.object_id,
        object_number=row.object_number,
        created_at=row.created_at,
        read=row.read_at is not None,
    )


def add_in(
    session: AsyncSession,
    user_ids: Sequence[int],
    *,
    kind: str,
    tab: str,
    title: str,
    subtitle: str | None = None,
    object_kind: str | None = None,
    object_id: str | None = None,
    object_number: str | None = None,
) -> None:
    """Уведомление каждому из `user_ids` — в транзакции вызывающего (откат откатывает и его)."""
    for user_id in dict.fromkeys(user_ids):
        session.add(
            StaffNotification(
                user_id=user_id,
                kind=kind,
                tab=tab,
                title=title[:200],
                subtitle=subtitle[:200] if subtitle else None,
                object_kind=object_kind,
                object_id=object_id,
                object_number=object_number,
            )
        )


class StaffNotificationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sessions = sessions
        self._clock = clock

    async def add(self, user_ids: Sequence[int], **fields: str | None) -> None:
        """Отдельной транзакцией: для событий вне транзакции сервиса (привязка Telegram)."""
        async with self._sessions() as session, session.begin():
            add_in(session, user_ids, **fields)  # type: ignore[arg-type]

    async def list(self, user_id: int) -> list[NotificationView]:
        stmt = (
            select(StaffNotification)
            .where(StaffNotification.user_id == user_id)
            .order_by(StaffNotification.created_at.desc(), StaffNotification.id.desc())
            .limit(LIST_LIMIT)
        )
        async with self._sessions() as session:
            return [_view(row) for row in (await session.scalars(stmt)).all()]

    async def unread_count(self, user_id: int) -> int:
        stmt = select(func.count()).where(
            StaffNotification.user_id == user_id, StaffNotification.read_at.is_(None)
        )
        async with self._sessions() as session:
            return int(await session.scalar(stmt) or 0)

    async def mark_read(self, user_id: int, notification_id: int) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(StaffNotification, notification_id, with_for_update=True)
            if row is None or row.user_id != user_id:
                raise NotFoundError("notification not found")
            if row.read_at is None:
                row.read_at = self._clock()

    async def mark_all_read(self, user_id: int) -> int:
        stmt = (
            update(StaffNotification)
            .where(StaffNotification.user_id == user_id, StaffNotification.read_at.is_(None))
            .values(read_at=self._clock())
        )
        async with self._sessions() as session, session.begin():
            result = await session.execute(stmt)
            return int(getattr(result, "rowcount", 0) or 0)
