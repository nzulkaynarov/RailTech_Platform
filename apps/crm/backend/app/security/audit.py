"""Журнал аудита мутаций (SPEC §11): кто, что, над чем, до/после.

Запись — в транзакции вызывающего, поэтому откат мутации откатывает и аудит.
"""

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuditLog

ActorType = Literal["user", "system", "bot"]


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: int | None
    type: ActorType = "user"
    ip: str | None = None

    @classmethod
    def system(cls) -> "Actor":
        return cls(user_id=None, type="system")


async def record(
    session: AsyncSession,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: object | None,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor.user_id,
            actor_type=actor.type,
            action=action,
            entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id),
            before=before,
            after=after,
            ip=actor.ip,
        )
    )
