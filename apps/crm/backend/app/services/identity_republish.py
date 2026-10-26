"""Переопубликация снимков сотрудников на шину (E7b, находка гейта C1-G-3).

Подписчик, появившийся позже сотрудников (EDS на стенде или проде с уже заведённой командой), не
видит их `identity.user.created`: проекции нет, и вход даёт 403 `USER_NOT_PROVISIONED`. Правка
«ничего не меняющая» события не даёт, поэтому здесь — явная команда: по `identity.user.updated.v1`
с полным снимком (с `permissions.eds`) на каждого сотрудника.

События идут обычным путём — `app.bus.events.user_updated` пишет строку outbox той же транзакцией,
что и чтение снимка; пачками по `BATCH_SIZE` сотрудников, ошибка пачки откатывает только её.
`changed_fields` не передаётся (поле необязательное, подсказка подписчику; менять нечего).
Идемпотентно: у события новый `id`, снимок тот же и с тем же `updated_at` — проекция применяет
«не старее» (`updated_at <=`), повтор безвреден, а более новая правка не затирается. Строки
сотрудников не меняются (`updated_at` не двигается).
"""

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.models.auth import User
from app.repositories import users as repo
from app.security.audit import Actor

logger = structlog.get_logger(__name__)

BATCH_SIZE = 50


@dataclass(frozen=True)
class RepublishResult:
    users: int  # сколько сотрудников в выборке
    published: int  # сколько событий записано в outbox (при dry-run — 0)


async def _user_ids(session: AsyncSession, user_id: int | None) -> list[int]:
    if user_id is not None:
        return [user_id] if await session.get(User, user_id) is not None else []
    return [user.id for user in await repo.list_users(session)]


async def republish_identity(
    sessions: async_sessionmaker[AsyncSession],
    *,
    user_id: int | None = None,
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE,
) -> RepublishResult:
    """Опубликовать `identity.user.updated.v1` всем сотрудникам (или одному, `user_id`).

    Неактивные тоже: подписчик должен знать, что доступа у них нет. `dry_run` только считает."""
    async with sessions() as session:
        ids = await _user_ids(session, user_id)
    if dry_run:
        return RepublishResult(users=len(ids), published=0)
    actor = Actor.system()
    published = 0
    for start in range(0, len(ids), batch_size):
        async with sessions() as session, session.begin():
            for uid in ids[start : start + batch_size]:
                user = await repo.get(session, uid)
                if user is None:  # удалён между выборкой и пачкой
                    continue
                await bus_events.user_updated(session, user, actor)
                published += 1
    logger.info("identity_republished", users=len(ids), published=published)
    return RepublishResult(users=len(ids), published=published)
