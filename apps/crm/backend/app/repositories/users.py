"""Доступ к пользователям и ролям."""

from collections.abc import Sequence

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Role, User, UserRole


async def get(session: AsyncSession, user_id: int, *, for_update: bool = False) -> User | None:
    stmt = select(User).where(User.id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


async def by_email(session: AsyncSession, email: str, *, for_update: bool = False) -> User | None:
    stmt = select(User).where(User.email == email.strip().lower())
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


async def by_tg_user_id(session: AsyncSession, tg_user_id: int) -> User | None:
    stmt = select(User).where(User.tg_user_id == tg_user_id, User.is_active.is_(True))
    return (await session.scalars(stmt)).first()


async def list_users(session: AsyncSession) -> Sequence[User]:
    return (await session.scalars(select(User).order_by(User.id))).all()


async def roles_of(session: AsyncSession, user_id: int) -> list[str]:
    stmt = (
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .order_by(Role.name)
    )
    return list((await session.scalars(stmt)).all())


async def roles_by_user(session: AsyncSession) -> dict[int, list[str]]:
    stmt = select(UserRole.user_id, Role.name).join(Role, Role.id == UserRole.role_id)
    result: dict[int, list[str]] = {}
    for user_id, name in (await session.execute(stmt)).all():
        result.setdefault(user_id, []).append(name)
    return {k: sorted(v) for k, v in result.items()}


async def set_roles(
    session: AsyncSession, user_id: int, roles: Sequence[str], granted_by: int | None
) -> None:
    await session.execute(delete(UserRole).where(UserRole.user_id == user_id))
    ids = (await session.scalars(select(Role.id).where(Role.name.in_(roles)))).all()
    for role_id in ids:
        session.add(UserRole(user_id=user_id, role_id=role_id, granted_by=granted_by))
    await session.flush()


async def count_active_admins(session: AsyncSession, *, excluding: int | None = None) -> int:
    stmt = (
        select(func.count(func.distinct(User.id)))
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name == "admin", User.is_active.is_(True))
    )
    if excluding is not None:
        stmt = stmt.where(User.id != excluding)
    return int(await session.scalar(stmt) or 0)


async def lock_admin_set(session: AsyncSession) -> None:
    """Сериализует изменения ролей/активности админов (инвариант «≥ 1 админ»)."""
    await session.execute(select(Role.id).where(Role.name == "admin").with_for_update())


async def set_erp_sync_error(session: AsyncSession, user_id: int, message: str | None) -> None:
    """Итог синхронизации с ERP: ошибка (для ленты внешних сервисов) или `None` — всё в порядке."""
    await session.execute(update(User).where(User.id == user_id).values(erp_sync_error=message))


# Задачи синхронизации с ERP в очереди или в работе: блокировка `erp_user:<id>`
# (`tasks/erp_users.py`).
_PENDING_ERP_SYNC = text(
    """
    SELECT DISTINCT CAST(substr(lock, length('erp_user:') + 1) AS bigint)
    FROM procrastinate_jobs
    WHERE task_name IN ('erp_provision_user', 'erp_revoke_sessions')
      AND status IN ('todo', 'doing')
      AND lock LIKE 'erp_user:%'
    """
)


async def erp_sync_pending_ids(session: AsyncSession, user_id: int | None = None) -> set[int]:
    """Пользователи, чья синхронизация с ERP стоит в очереди или выполняется (итог `pending`)."""
    ids = {int(row[0]) for row in await session.execute(_PENDING_ERP_SYNC)}
    return ids if user_id is None else ids & {user_id}
