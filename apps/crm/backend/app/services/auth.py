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
from app.domain.errors import (
    AccountLockedError,
    AuthError,
    Reason,
    SecondFactorCodeError,
    SecondFactorSetupError,
)
from app.models.auth import RefreshToken, User
from app.repositories import users as repo
from app.security import audit, reauth, second_factor
from app.security.audit import Actor
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.second_factor import FactorClaims
from app.security.secrets_store import SecretCipher, SecretsKeyError
from app.security.tokens import (
    AccessClaims,
    TokenError,
    closed_by_password_change,
    hash_refresh_token,
    issue_access,
    new_family,
    new_refresh_token,
    password_version,
)
from app.services.second_factor import FactorSetup, SecondFactorService, factor_required

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
class SecondFactorRequired:
    """Пароль верен, нужен код второго фактора (ДВ-4): сессии ещё нет, `challenge` — на 5 минут."""

    challenge: str


@dataclass(frozen=True, slots=True)
class EnrollmentRequired:
    """Пароль верен, фактор обязателен по разделам доступа, но не настроен (ДВ-4б): сессии нет,
    `challenge` — на 15 минут, им настраивают фактор (`enroll_setup`, `enroll_complete`)."""

    challenge: str


@dataclass(frozen=True, slots=True)
class Enrolled:
    session: Session
    backup_codes: list[str]


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None


class AuthService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessions = sessions
        self._settings = settings

    @property
    def _key(self) -> bytes:
        return self._settings.jwt_secret.get_secret_value().encode()

    def _trusted_device(self, user: User, device_token: str | None) -> bool:
        """Метка «запомнить устройство» этого сотрудника при тех же версиях пароля и фактора."""
        if not device_token:
            return False
        try:
            claims = second_factor.decode_device(self._key, device_token)
        except TokenError:
            return False
        return (
            claims.user_id == user.id
            and claims.password_version == password_version(user.password_changed_at)
            and claims.factor_version == second_factor.version_of(user.totp_enabled_at)
        )

    async def login(
        self, email: str, password: str, client: ClientInfo, device_token: str | None = None
    ) -> Session | SecondFactorRequired | EnrollmentRequired:
        """Пароль; у сотрудника со вторым фактором — `SecondFactorRequired`, если устройство не
        запомнено (ДВ-4). Сессию тогда выдаёт `second_factor`. Фактор обязателен по разделам
        доступа, но не настроен — `EnrollmentRequired` (ДВ-4б): входа без фактора нет."""
        now = datetime.now(UTC)
        failure: AuthError | None = None
        result: Session | SecondFactorRequired | EnrollmentRequired
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
                user.failed_logins, user.locked_until = 0, None
                if user.totp_enabled_at is not None and not self._trusted_device(
                    user, device_token
                ):
                    claims = FactorClaims(user.id, password_version(user.password_changed_at))
                    result = SecondFactorRequired(
                        second_factor.issue_challenge(self._key, claims, now)
                    )
                elif user.totp_enabled_at is None and await factor_required(
                    session, user, self._settings
                ):
                    claims = FactorClaims(user.id, password_version(user.password_changed_at))
                    result = EnrollmentRequired(second_factor.issue_enroll(self._key, claims, now))
                    await audit.record(
                        session,
                        Actor(user.id, ip=client.ip),
                        "auth.enrollment_required",
                        "user",
                        user.id,
                    )
                else:
                    user.last_login_at = now
                    result = await self._issue(session, user, new_family(), client, now)
                    await audit.record(
                        session, Actor(user.id, ip=client.ip), "auth.login", "user", user.id
                    )
        if failure is not None:
            raise failure
        return result

    def _enroll_claims(self, token: str) -> FactorClaims:
        try:
            return second_factor.decode_enroll(self._key, token)
        except TokenError as exc:
            raise AuthError("second factor challenge expired") from exc

    @staticmethod
    def _enrollable(user: User | None, claims: FactorClaims) -> User:
        if (
            user is None
            or not user.is_active
            or user.totp_enabled_at is not None
            or claims.password_version != password_version(user.password_changed_at)
        ):
            raise AuthError("second factor challenge expired")
        return user

    async def enroll_setup(self, challenge: str, issuer: str, client: ClientInfo) -> FactorSetup:
        """Секрет и адрес для QR при входе, когда фактор обязателен, но не настроен (ДВ-4б)."""
        claims = self._enroll_claims(challenge)
        service = SecondFactorService(self._sessions, self._settings)
        async with self._sessions() as session, session.begin():
            user = self._enrollable(
                await repo.get(session, claims.user_id, for_update=True), claims
            )
            return await service.setup_locked(session, Actor(user.id, ip=client.ip), user, issuer)

    async def enroll_complete(self, challenge: str, code: str, client: ClientInfo) -> Enrolled:
        """Код из приложения включает фактор и открывает сессию одной транзакцией (ДВ-4б);
        резервные коды — в ответе, один раз. Неверный код — в счёт блокировки."""
        now = datetime.now(UTC)
        claims = self._enroll_claims(challenge)
        service = SecondFactorService(self._sessions, self._settings)
        failure: Exception | None = None
        enrolled: Enrolled | None = None
        async with self._sessions() as session, session.begin():
            user = self._enrollable(
                await repo.get(session, claims.user_id, for_update=True), claims
            )
            if user.locked_until is not None and user.locked_until > now:
                raise AccountLockedError("account locked", until=user.locked_until.isoformat())
            actor = Actor(user.id, ip=client.ip)
            try:
                codes = await service.enable_locked(session, actor, user, code, now)
            except SecondFactorSetupError as exc:
                if exc.details.get("reason") != Reason.SECOND_FACTOR_CODE_INVALID.value:
                    raise
                failure = self._register_failure(user, now)
                if not isinstance(failure, AccountLockedError):
                    failure = SecondFactorCodeError("invalid second factor code")
            else:
                user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
                enrolled = Enrolled(
                    await self._issue(session, user, new_family(), client, now), codes
                )
                await audit.record(session, actor, "auth.login", "user", user.id)
        if failure is not None:
            raise failure
        assert enrolled is not None  # noqa: S101 — set whenever no failure was recorded
        return enrolled

    async def second_factor(
        self, challenge: str, code: str, remember: bool, client: ClientInfo
    ) -> tuple[Session, str | None]:
        """Код приложения или резервный код после пароля (ДВ-4). Неверный код — в счёт блокировки.
        `remember` — метка устройства на 30 дней (второй элемент результата)."""
        now = datetime.now(UTC)
        try:
            claims = second_factor.decode_challenge(self._key, challenge)
        except TokenError as exc:
            raise AuthError("second factor challenge expired") from exc
        failure: AuthError | None = None
        device: str | None = None
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, claims.user_id, for_update=True)
            if (
                user is None
                or not user.is_active
                or user.totp_enabled_at is None
                or user.totp_secret is None
                or claims.password_version != password_version(user.password_changed_at)
            ):
                raise AuthError("second factor challenge expired")
            if user.locked_until is not None and user.locked_until > now:
                raise AccountLockedError("account locked", until=user.locked_until.isoformat())
            step = second_factor.accept_code(
                self._secret(user.totp_secret), code, user.totp_last_step, now
            )
            remaining = (
                None
                if step is not None
                else second_factor.consume_backup_code(user.totp_backup_codes, code)
            )
            if step is None and remaining is None:
                failure = self._register_failure(user, now)
                if not isinstance(failure, AccountLockedError):
                    failure = SecondFactorCodeError("invalid second factor code")
                await audit.record(
                    session,
                    Actor(user.id, ip=client.ip),
                    "auth.second_factor_failed",
                    "user",
                    user.id,
                )
            else:
                if step is not None:
                    user.totp_last_step = step
                else:
                    user.totp_backup_codes = remaining or []
                    await audit.record(
                        session,
                        Actor(user.id, ip=client.ip),
                        "auth.backup_code_used",
                        "user",
                        user.id,
                    )
                user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
                result = await self._issue(session, user, new_family(), client, now)
                if remember:
                    device = second_factor.issue_device(
                        self._key,
                        FactorClaims(
                            user.id,
                            password_version(user.password_changed_at),
                            second_factor.version_of(user.totp_enabled_at),
                        ),
                        now,
                    )
                await audit.record(
                    session, Actor(user.id, ip=client.ip), "auth.login", "user", user.id
                )
        if failure is not None:
            raise failure
        return result, device

    def _secret(self, ciphertext: bytes) -> str:
        cipher = SecretCipher.optional(self._settings.secrets_key.get_secret_value())
        if cipher is None:
            raise AuthError("second factor unavailable: no encryption key for secrets")
        try:
            return cipher.decrypt(ciphertext)
        except SecretsKeyError as exc:
            raise AuthError("second factor unavailable: secrets encryption key replaced") from exc

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
