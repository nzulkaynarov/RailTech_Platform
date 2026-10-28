"""Сотрудники для выбора: кому передать лида и кто исполнитель раздела каталога (D1-8, B-007).

Раздел — ключ каталога `platform-rbac.yaml` (`erp.calc.goods`, `eds.payments`, …). Сотрудник входит
в выборку, если объединение матриц его ролей Платформы даёт раздел на нужном уровне (`full` ⊇
`read`). Матрицы системных ролей берутся из каталога, остальных — из данных роли (как при
вычислении прав). Сотрудник без ролей Платформы (старый вход по базовой роли) раздела не имеет.
Отдаются только id, имя, инициалы и должность: почта, телефон и роли наружу не уходят.
"""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import ValidationFailedError
from app.domain.platform_roles import RoleGrant, merge_access
from app.domain.platform_roles_generated import RESOURCE_KEYS
from app.repositories import platform_roles as prepo
from app.repositories import users as users_repo
from app.schemas.leads import TeamMember
from app.services.user_platform import role_refs

Level = Literal["full", "read"]
_RANK = {"read": 1, "full": 2}


def initials_of(name: str, email: str = "") -> str:
    """Инициалы для аватара: первые буквы двух первых слов имени, иначе первая буква почты."""
    letters = "".join(part[0] for part in name.split()[:2]).upper()
    return (letters or email[:1].upper())[:3]


def checked_section(section: str) -> str:
    """Раздел должен быть в каталоге: опечатка — 422, а не пустой список."""
    if section not in RESOURCE_KEYS:
        raise ValidationFailedError(f"unknown section: {section}", field="section")
    return section


async def by_section(session: AsyncSession, section: str, level: Level) -> list[TeamMember]:
    """Активные сотрудники, у которых раздел на уровне не ниже `level`; по имени."""
    checked_section(section)
    users = await users_repo.list_users(session)
    held = await prepo.roles_by_user(session)
    members: list[TeamMember] = []
    for user in users:
        if not user.is_active:
            continue
        access = merge_access(RoleGrant(ref.access) for ref in role_refs(held.get(user.id, [])))
        if _RANK.get(access.get(section, ""), 0) >= _RANK[level]:
            members.append(member_of(user.full_name, user.email, user.id, user.position))
    members.sort(key=lambda m: (m.full_name.casefold(), m.id))
    return members


def member_of(full_name: str, email: str, user_id: int, position: str | None) -> TeamMember:
    return TeamMember(
        id=user_id,
        full_name=full_name,
        initials=initials_of(full_name, email),
        position=position or None,
    )


async def workers(session: AsyncSession) -> list[TeamMember]:
    """Активные менеджеры и админы (базовая роль CRM — признак «ведёт лидов»): кому передать."""
    users = await users_repo.list_users(session)
    roles = await users_repo.roles_by_user(session)
    return [
        member_of(u.full_name, u.email, u.id, u.position)
        for u in users
        if u.is_active and {"manager", "admin"} & set(roles.get(u.id, []))
    ]
