"""Аутентификация (SPEC §11, ADR-0005): вход, lockout, ротация refresh, выход.

Refresh-токены — семейства: каждый refresh выдаёт новый токен и отзывает
старый; повторное использование отозванного токена отзывает всё семейство
(признак кражи). Хранится только sha256 токена.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import AccountLockedError, AuthError
from app.models.auth import RefreshToken, User
from app.repositories import users as repo
from app.security import audit, reauth
from app.security.audit import Actor
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import (
    AccessClaims,
    closed_by_password_change,
    hash_refresh_token,
    issue_access,
    new_family,
    new_refresh_token,
    password_version,
)

logger = structlog.get_logger(__name__)

# Хэш для выравнивания времени ответа при неизвестном email.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-password-1")


@dataclass(frozen=True, slots=True)
class Session:
    access_token: str
    refresh_token: str
    user_id: int
    roles: list[str]
    must_change_password: bool


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None


class AuthService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessions = sessions
        self._settings = settings

    async def login(self, email: str, password: str, client: ClientInfo) -> Session:
        now = datetime.now(UTC)
        failure: AuthError | None = None
        async with self._sessions() as session, session.begin():
            user = await repo.by_email(session, email, for_update=True)
            if user is None or not user.is_active:
                verify_password(_DUMMY_HASH, password)
                raise AuthError("invalid credentials")
            if user.locked_until is not None and user.locked_until > now:
                raise AccountLockedError("account locked", until=user.locked_until.isoformat())
            if not verify_password(user.password_hash, password):
                # Счётчик неудач фиксируется коммитом; ошибка — после транзакции.
                failure = self._register_failure(user, now)
                await audit.record(
                    session, Actor(user.id, ip=client.ip), "auth.login_failed", "user", user.id
                )
            else:
                if needs_rehash(user.password_hash):
                    user.password_hash = hash_password(password)
                user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
                result = await self._issue(session, user, new_family(), client, now)
                await audit.record(
                    session, Actor(user.id, ip=client.ip), "auth.login", "user", user.id
                )
        if failure is not None:
            raise failure
        return result

    async def refresh(self, token: str, client: ClientInfo) -> Session:
        now = datetime.now(UTC)
        reused = closed = False
        async with self._sessions() as session, session.begin():
            row = await _token(session, token)
            if row is None:
                raise AuthError("invalid refresh token")
            if row.revoked_at is not None:
                await _revoke_family(session, row.family, now)
                logger.warning("refresh_token_reuse", user_id=row.user_id)
                reused = True
            else:
                if row.expires_at <= now:
                    raise AuthError("refresh token expired")
                user = await repo.get(session, row.user_id)
                if user is None or not user.is_active:
                    raise AuthError("user inactive")
                if closed_by_password_change(row.created_at, user.password_changed_at):
                    # Токен выпущен до смены пароля (гонка refresh и сброса): сессия закрыта.
                    await _revoke_family(session, row.family, now)
                    closed = True  # ошибка — после коммита, иначе откат отменит отзыв семейства
                else:
                    row.revoked_at = now
                    result = await self._issue(session, user, row.family, client, now)
        if closed:
            raise AuthError("session closed by a password change")
        if reused:
            raise AuthError("refresh token reused")
        return result

    async def reissue(self, user_id: int, client: ClientInfo, at: datetime) -> Session:
        """Новая сессия после смены пароля: прежние закрыты, эта рабочая (новое семейство токенов).

        `at` — момент смены пароля: токены выпускаются на него, чтобы отсечка по
        `password_changed_at` их не задела."""
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id)
            if user is None or not user.is_active:
                raise AuthError("user inactive")
            return await self._issue(session, user, new_family(), client, at)

    async def logout(self, token: str) -> None:
        async with self._sessions() as session, session.begin():
            row = await _token(session, token)
            if row is not None:
                await _revoke_family(session, row.family, datetime.now(UTC))

    def _register_failure(self, user: User, now: datetime) -> AuthError:
        policy = reauth.LockoutPolicy(
            self._settings.login_max_failures, self._settings.login_lockout_minutes
        )
        if reauth.register_failure(user, now, policy):
            return reauth.locked_error(user)
        return AuthError("invalid credentials")

    async def _issue(
        self, session: AsyncSession, user: User, family: str, client: ClientInfo, now: datetime
    ) -> Session:
        roles = await repo.roles_of(session, user.id)
        refresh = new_refresh_token()
        session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_refresh_token(refresh),
                family=family,
                created_at=now,
                expires_at=now + timedelta(days=self._settings.refresh_token_ttl_days),
                user_agent=(client.user_agent or "")[:255] or None,
                ip=client.ip,
            )
        )
        access = issue_access(
            self._settings.jwt_secret.get_secret_value().encode(),
            AccessClaims(
                user.id,
                tuple(roles),
                user.must_change_password,
                password_version(user.password_changed_at),
            ),
            self._settings.access_token_ttl_s,
            now,
        )
        return Session(access, refresh, user.id, roles, user.must_change_password)


async def _token(session: AsyncSession, token: str) -> RefreshToken | None:
    stmt = (
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(token))
        .with_for_update()
    )
    return (await session.scalars(stmt)).first()


async def _revoke_family(session: AsyncSession, family: str, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family == family, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
