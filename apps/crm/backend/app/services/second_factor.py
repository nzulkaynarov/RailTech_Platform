"""Включение и отключение второго фактора сотрудником (ДВ-4, реестр рисков Д1).

Настройка в два шага: `setup` выдаёт секрет и адрес для QR (секрет хранится как «начатый»),
`enable` принимает код из приложения и включает фактор, возвращая резервные коды — один раз.
Отключение — тем же кодом или резервным.

ДВ-4б: обязательность по разделам (`domain/second_factor_policy.py`) — вход держателя без фактора
идёт через настройку (`AuthService.enroll_*`), отключить такой фактор нельзя; сброс администратором
(с причиной и записью в журнале); «свежий код» (step-up, 5 минут) перед чувствительными действиями.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain import second_factor_policy as policy
from app.domain.errors import (
    SECOND_FACTOR_NOT_ENROLLED,
    SECOND_FACTOR_REQUIRED,
    SECOND_FACTOR_SELF_RESET,
    ConflictError,
    NotFoundError,
    Reason,
    SecondFactorSetupError,
    StepUpRequiredError,
)
from app.domain.platform_roles import RoleGrant, merge_access
from app.models.auth import RefreshToken, User
from app.repositories import platform_roles as prepo
from app.repositories import users as repo
from app.security import audit, reauth, second_factor
from app.security.audit import Actor
from app.security.second_factor import FactorClaims
from app.security.secrets_store import SecretCipher, SecretsKeyError
from app.security.tokens import TokenError, password_version
from app.services.user_platform import role_refs

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FactorStatus:
    enabled: bool
    enabled_at: datetime | None
    backup_codes_left: int
    required: bool = False


@dataclass(frozen=True, slots=True)
class FactorSetup:
    secret: str
    otpauth_uri: str


async def access_of(session: AsyncSession, user_id: int) -> dict[str, str]:
    """Effective permission sections of an employee: union of the matrices of all his roles."""
    held = await prepo.roles_of_user(session, user_id)
    return merge_access(RoleGrant(ref.access) for ref in role_refs(held))


async def factor_required(session: AsyncSession, user: User, settings: Settings) -> bool:
    """Is the second factor mandatory for this employee now (from his sections, not role names).

    Without the secrets encryption key no factor can exist at all (the profile cannot enable it
    either), so the rule would only lock the whole company out: it stays inactive and says so in
    the log instead."""
    required = policy.factor_required(await access_of(session, user.id), is_active=user.is_active)
    if required and SecretCipher.optional(settings.secrets_key.get_secret_value()) is None:
        logger.warning("second_factor_required_but_unavailable", user_id=user.id)
        return False
    return required


@dataclass(frozen=True, slots=True)
class StepUpToken:
    token: str
    expires_in: int


class SecondFactorService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessions = sessions
        self._settings = settings

    def _cipher(self) -> SecretCipher:
        cipher = SecretCipher.optional(self._settings.secrets_key.get_secret_value())
        if cipher is None:
            raise SecondFactorSetupError(
                "encryption is not configured", reason=Reason.SECRETS_KEY_MISSING
            )
        return cipher

    def _decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._cipher().decrypt(ciphertext)
        except SecretsKeyError as exc:
            raise SecondFactorSetupError(
                "encryption was reconfigured", reason=Reason.SECRETS_KEY_MISSING
            ) from exc

    async def status(self, user_id: int) -> FactorStatus:
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
            if user is None:
                raise NotFoundError("user not found")
            return FactorStatus(
                user.totp_enabled_at is not None,
                user.totp_enabled_at,
                len(user.totp_backup_codes or []),
                await factor_required(session, user, self._settings),
            )

    async def setup(self, actor: Actor, user_id: int, issuer: str) -> FactorSetup:
        self._cipher()
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            return await self.setup_locked(session, actor, user, issuer)

    async def setup_locked(
        self, session: AsyncSession, actor: Actor, user: User, issuer: str
    ) -> FactorSetup:
        cipher = self._cipher()
        if user.totp_enabled_at is not None:
            raise SecondFactorSetupError(
                "already enabled", reason=Reason.SECOND_FACTOR_ALREADY_ENABLED
            )
        secret = second_factor.new_secret()
        user.totp_pending_secret = cipher.encrypt(secret)
        await audit.record(session, actor, "auth.second_factor_setup", "user", user.id)
        return FactorSetup(secret, second_factor.otpauth_uri(secret, user.email, issuer))

    async def enable(self, actor: Actor, user_id: int, code: str) -> list[str]:
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            return await self.enable_locked(session, actor, user, code, now)

    async def enable_locked(
        self, session: AsyncSession, actor: Actor, user: User, code: str, now: datetime
    ) -> list[str]:
        """Confirm the pending secret with a code and switch the factor on (user row is locked by
        the caller; also used by the enrollment at sign-in, in one transaction with the session)."""
        if user.totp_enabled_at is not None:
            raise SecondFactorSetupError(
                "already enabled", reason=Reason.SECOND_FACTOR_ALREADY_ENABLED
            )
        if user.totp_pending_secret is None:
            raise SecondFactorSetupError(
                "setup not started", reason=Reason.SECOND_FACTOR_NOT_STARTED
            )
        secret = self._decrypt(user.totp_pending_secret)
        step = second_factor.accept_code(secret, code, None, now)
        if step is None:
            raise SecondFactorSetupError("invalid code", reason=Reason.SECOND_FACTOR_CODE_INVALID)
        codes, hashes = second_factor.new_backup_codes()
        user.totp_secret, user.totp_pending_secret = user.totp_pending_secret, None
        user.totp_enabled_at, user.totp_last_step = now, step
        user.totp_backup_codes = hashes
        await audit.record(session, actor, "auth.second_factor_enabled", "user", user.id)
        return codes

    async def disable(self, actor: Actor, user_id: int, code: str) -> None:
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            if user.totp_enabled_at is None or user.totp_secret is None:
                raise SecondFactorSetupError("not enabled", reason=Reason.SECOND_FACTOR_NOT_ENABLED)
            if await factor_required(session, user, self._settings):
                # Required by the held sections: switching it off would only send him to enrollment
                # at the next sign-in, and a hijacked session must not be able to drop the factor.
                raise ConflictError(
                    "the second factor is required for this access",
                    reason=SECOND_FACTOR_REQUIRED,
                )
            secret = self._decrypt(user.totp_secret)
            accepted = second_factor.accept_code(secret, code, user.totp_last_step, now)
            if (
                accepted is None
                and second_factor.consume_backup_code(user.totp_backup_codes, code) is None
            ):
                raise SecondFactorSetupError(
                    "invalid code", reason=Reason.SECOND_FACTOR_CODE_INVALID
                )
            user.totp_secret = user.totp_pending_secret = None
            user.totp_enabled_at = user.totp_last_step = None
            user.totp_backup_codes = []
            await audit.record(session, actor, "auth.second_factor_disabled", "user", user.id)

    async def reset(self, actor: Actor, user_id: int, reason: str) -> None:
        """Admin resets the factor of an employee (lost phone): journal entry with the reason, the
        employee's sessions end, at the next sign-in he enrolls again (if the factor is required) or
        signs in with the password only (if not)."""
        if actor.user_id == user_id:
            raise ConflictError(
                "reset your own factor is not allowed", reason=SECOND_FACTOR_SELF_RESET
            )
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            if user.totp_enabled_at is None:
                raise SecondFactorSetupError("not enabled", reason=Reason.SECOND_FACTOR_NOT_ENABLED)
            user.totp_secret = user.totp_pending_secret = None
            user.totp_enabled_at = user.totp_last_step = None
            user.totp_backup_codes = []
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            await audit.record(
                session,
                actor,
                "auth.second_factor_reset",
                "user",
                user_id,
                after={"reason": reason.strip()},
            )

    def _claims(self, user: User) -> FactorClaims:
        return FactorClaims(
            user.id,
            password_version(user.password_changed_at),
            second_factor.version_of(user.totp_enabled_at),
        )

    @property
    def _key(self) -> bytes:
        return self._settings.jwt_secret.get_secret_value().encode()

    async def step_up(self, actor: Actor, user_id: int, code: str) -> StepUpToken:
        """A fresh code (app or backup) -> a token valid 5 minutes for sensitive actions. A wrong
        code counts to the lockout like at sign-in."""
        now = datetime.now(UTC)
        failure: Exception | None = None
        token = ""
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
            if user.totp_enabled_at is None or user.totp_secret is None:
                raise StepUpRequiredError(
                    "second factor is not enrolled", reason=SECOND_FACTOR_NOT_ENROLLED
                )
            if reauth.is_locked(user, now):
                raise reauth.locked_error(user)
            step = second_factor.accept_code(
                self._decrypt(user.totp_secret), code, user.totp_last_step, now
            )
            remaining = (
                None
                if step is not None
                else second_factor.consume_backup_code(user.totp_backup_codes, code)
            )
            if step is None and remaining is None:
                policy_ = reauth.LockoutPolicy(
                    self._settings.login_max_failures, self._settings.login_lockout_minutes
                )
                locked = reauth.register_failure(user, now, policy_)
                failure = (
                    reauth.locked_error(user)
                    if locked
                    else SecondFactorSetupError(
                        "invalid code", reason=Reason.SECOND_FACTOR_CODE_INVALID
                    )
                )
                await audit.record(session, actor, "auth.step_up_failed", "user", user.id)
            else:
                if step is not None:
                    user.totp_last_step = step
                else:
                    user.totp_backup_codes = remaining or []
                user.failed_logins = 0
                token = second_factor.issue_step_up(self._key, self._claims(user), now)
                await audit.record(session, actor, "auth.step_up", "user", user.id)
        if failure is not None:
            raise failure
        return StepUpToken(token, int(second_factor.STEP_UP_TTL.total_seconds()))

    async def require_step_up(self, user_id: int, token: str | None) -> None:
        """Server-side check of the fresh code (employees the policy asks no factor from, with none
        enrolled, have nothing to confirm): no token, expired, of another employee or issued
        before the password or the factor changed -> `StepUpRequiredError` (403)."""
        async with self._sessions() as session:
            user = await repo.get(session, user_id)
            if user is None or not user.is_active:
                raise StepUpRequiredError("user inactive")
            if user.totp_enabled_at is None:
                if not await factor_required(session, user, self._settings):
                    return  # the policy asks no factor from this employee: nothing to confirm
                # Required but not enrolled (session opened before the rule): enrol first.
                raise StepUpRequiredError(
                    "second factor is not enrolled", reason=SECOND_FACTOR_NOT_ENROLLED
                )
        if not token:
            raise StepUpRequiredError("a fresh second factor code is required")
        try:
            claims = second_factor.decode_step_up(self._key, token)
        except TokenError as exc:
            raise StepUpRequiredError("the second factor code is stale") from exc
        if claims != self._claims(user):
            raise StepUpRequiredError("the second factor code is stale")
