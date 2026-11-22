"""Секретная ссылка на личный календарь сотрудника (iCal-подписка).

Токен — 32 случайных байта (base64url), показывается один раз при выдаче; в CRM остаётся только
sha256. Повторная выдача заменяет хеш: старая ссылка перестаёт действовать. Сам календарь
собирает BFF по снимку очереди живой сессии; CRM хранит хеш как запись о выдаче и отзывает его с
отключением сотрудника.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import NotFoundError
from app.repositories import users as repo
from app.security import audit
from app.security.audit import Actor

TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


@dataclass(frozen=True, slots=True)
class IssuedLink:
    token: str
    token_hash: str
    issued_at: datetime


class CalendarLinkService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def issue(self, actor: Actor, user_id: int) -> IssuedLink:
        """Выдать новую ссылку; прежняя (если была) перестаёт действовать."""
        token = secrets.token_urlsafe(TOKEN_BYTES)
        digest = hash_token(token)
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None or not user.is_active:
                raise NotFoundError("user not found")
            user.calendar_token_hash = digest
            user.calendar_token_at = now
            await audit.record(session, actor, "me.calendar_link_issued", "user", user.id)
        return IssuedLink(token, digest, now)
