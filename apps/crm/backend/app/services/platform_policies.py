"""Правила casbin ролей Платформы: запись при изменении роли и сверка с таблицей при старте.

Субъект правила — `pr:<id>` (`domain/platform_roles.role_subject`), домен `crm`, объект и действие —
из каталога по матрице роли. Сотруднику субъекты ролей добавляются при проверке права
(`security/rbac.Rbac.allowed`), поэтому отдельных связей `g` не нужно.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.platform_roles import crm_policies, role_subject
from app.repositories import platform_roles as repo

logger = structlog.get_logger(__name__)


async def write_role_policies(session: AsyncSession, role_id: int, access: dict[str, str]) -> None:
    """Правила роли по её матрице (в транзакции роли)."""
    await repo.replace_policies(session, role_id, crm_policies(access))


async def sync_policies(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Привести правила `pr:*` в БД к таблице ролей; возвращает число исправленных ролей."""
    changed = 0
    async with sessions() as session, session.begin():
        roles = await repo.list_roles(session)
        current = await repo.policy_rows(session)
        wanted = {role_subject(r.id): crm_policies(r.access) for r in roles}
        stale = [subject for subject in current if subject not in wanted]
        await repo.delete_policies(session, stale)
        changed += len(stale)
        for role in roles:
            subject = role_subject(role.id)
            if current.get(subject, set()) != set(wanted[subject]):
                await write_role_policies(session, role.id, role.access)
                changed += 1
    if changed:
        logger.info("platform_role_policies_synced", roles=changed)
    return changed
