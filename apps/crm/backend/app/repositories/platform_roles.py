"""Доступ к ролям Платформы, их выдаче сотрудникам и политикам casbin (`pr:<id>`)."""

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.platform_roles import POLICY_DOMAIN, SUBJECT_PREFIX, role_subject
from app.models.auth import CasbinRule, User
from app.models.platform_roles import PlatformRole, UserPlatformRole


async def get(
    session: AsyncSession, role_id: int, *, for_update: bool = False
) -> PlatformRole | None:
    stmt = select(PlatformRole).where(PlatformRole.id == role_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


async def by_ids(session: AsyncSession, role_ids: Iterable[int]) -> list[PlatformRole]:
    stmt = select(PlatformRole).where(PlatformRole.id.in_(list(role_ids))).order_by(PlatformRole.id)
    return list((await session.scalars(stmt)).all())


async def by_codes(session: AsyncSession, codes: Iterable[str]) -> list[PlatformRole]:
    stmt = select(PlatformRole).where(PlatformRole.code.in_(list(codes))).order_by(PlatformRole.id)
    return list((await session.scalars(stmt)).all())


async def list_roles(session: AsyncSession) -> list[PlatformRole]:
    return list((await session.scalars(select(PlatformRole).order_by(PlatformRole.id))).all())


async def name_taken(session: AsyncSession, name: str, *, excluding: int | None = None) -> bool:
    stmt = select(func.count()).where(func.lower(PlatformRole.name) == name.strip().lower())
    if excluding is not None:
        stmt = stmt.where(PlatformRole.id != excluding)
    return bool(await session.scalar(stmt))


async def member_counts(session: AsyncSession) -> dict[int, int]:
    stmt = select(UserPlatformRole.role_id, func.count()).group_by(UserPlatformRole.role_id)
    return {rid: int(n) for rid, n in (await session.execute(stmt)).all()}


async def roles_of_user(session: AsyncSession, user_id: int) -> list[PlatformRole]:
    stmt = (
        select(PlatformRole)
        .join(UserPlatformRole, UserPlatformRole.role_id == PlatformRole.id)
        .where(UserPlatformRole.user_id == user_id)
        .order_by(PlatformRole.id)
    )
    return list((await session.scalars(stmt)).all())


async def roles_by_user(session: AsyncSession) -> dict[int, list[PlatformRole]]:
    stmt = (
        select(UserPlatformRole.user_id, PlatformRole)
        .join(PlatformRole, PlatformRole.id == UserPlatformRole.role_id)
        .order_by(PlatformRole.id)
    )
    result: dict[int, list[PlatformRole]] = {}
    for user_id, role in (await session.execute(stmt)).all():
        result.setdefault(user_id, []).append(role)
    return result


async def role_ids_of_user(session: AsyncSession, user_id: int) -> list[int]:
    stmt = select(UserPlatformRole.role_id).where(UserPlatformRole.user_id == user_id)
    return sorted((await session.scalars(stmt)).all())


async def rbac_identity(session: AsyncSession, user_id: int) -> tuple[tuple[int, ...], bool]:
    """Роли Платформы для проверки прав: (их id, есть ли системная роль «Администратор»)."""
    held = await roles_of_user(session, user_id)
    return tuple(r.id for r in held), any(r.code == "ADMIN" for r in held)


async def user_ids_of_role(session: AsyncSession, role_id: int) -> list[int]:
    stmt = select(UserPlatformRole.user_id).where(UserPlatformRole.role_id == role_id)
    return sorted((await session.scalars(stmt)).all())


async def set_user_roles(
    session: AsyncSession, user_id: int, role_ids: Sequence[int], granted_by: int | None
) -> None:
    keep = set(role_ids)
    held = set(await role_ids_of_user(session, user_id))
    if held - keep:
        await session.execute(
            delete(UserPlatformRole).where(
                UserPlatformRole.user_id == user_id, UserPlatformRole.role_id.in_(held - keep)
            )
        )
    for role_id in sorted(keep - held):
        session.add(UserPlatformRole(user_id=user_id, role_id=role_id, granted_by=granted_by))
    await session.flush()


async def count_active_holders(
    session: AsyncSession, role_id: int, *, excluding: int | None = None
) -> int:
    """Активные сотрудники с ролью (для инварианта «≥ 1 администратор и директор»)."""
    stmt = (
        select(func.count(func.distinct(User.id)))
        .join(UserPlatformRole, UserPlatformRole.user_id == User.id)
        .where(UserPlatformRole.role_id == role_id, User.is_active.is_(True))
    )
    if excluding is not None:
        stmt = stmt.where(User.id != excluding)
    return int(await session.scalar(stmt) or 0)


async def lock_system_roles(session: AsyncSession) -> None:
    """Сериализует изменения системных ролей и их держателей (инвариант «≥ 1 админ и директор»)."""
    await session.execute(
        select(PlatformRole.id).where(PlatformRole.is_system.is_(True)).with_for_update()
    )


# --- политики casbin ---------------------------------------------------------------------------


async def policy_rows(session: AsyncSession) -> dict[str, set[tuple[str, str]]]:
    """Текущие правила ролей Платформы в БД: субъект `pr:<id>` -> {(ресурс, действие)}."""
    stmt = select(CasbinRule.v0, CasbinRule.v2, CasbinRule.v3).where(
        CasbinRule.ptype == "p", CasbinRule.v0.like(f"{SUBJECT_PREFIX}%")
    )
    result: dict[str, set[tuple[str, str]]] = {}
    for subject, resource, action in (await session.execute(stmt)).all():
        if subject and resource and action:
            result.setdefault(subject, set()).add((resource, action))
    return result


async def replace_policies(
    session: AsyncSession, role_id: int, policies: Iterable[tuple[str, str]]
) -> None:
    """Правила casbin роли: заменить набор целиком (в той же транзакции, что и роль)."""
    subject = role_subject(role_id)
    await delete_policies(session, [subject])
    for resource, action in sorted(policies):
        session.add(CasbinRule(ptype="p", v0=subject, v1=POLICY_DOMAIN, v2=resource, v3=action))
    await session.flush()


async def delete_policies(session: AsyncSession, subjects: Iterable[str]) -> None:
    subject_list = list(subjects)
    if subject_list:
        await session.execute(
            delete(CasbinRule).where(CasbinRule.ptype == "p", CasbinRule.v0.in_(subject_list))
        )
