"""Включение и отключение второго фактора сотрудником (ДВ-4, реестр рисков Д1).

Настройка в два шага: `setup` выдаёт секрет и адрес для QR (секрет хранится как «начатый»),
`enable` принимает код из приложения и включает фактор, возвращая резервные коды — один раз.
Отключение — тем же кодом или резервным. Обязательность для ролей и сброс администратором —
следующий шаг (ДВ-4б).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import NotFoundError, Reason, SecondFactorSetupError
from app.repositories import users as repo
from app.security import audit, second_factor
from app.security.audit import Actor
from app.security.secrets_store import SecretCipher, SecretsKeyError


@dataclass(frozen=True, slots=True)
class FactorStatus:
    enabled: bool
    enabled_at: datetime | None
    backup_codes_left: int


@dataclass(frozen=True, slots=True)
class FactorSetup:
    secret: str
    otpauth_uri: str


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
            )

    async def setup(self, actor: Actor, user_id: int, issuer: str) -> FactorSetup:
        cipher = self._cipher()
        async with self._sessions() as session, session.begin():
            user = await repo.get(session, user_id, for_update=True)
            if user is None:
                raise NotFoundError("user not found")
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
                raise SecondFactorSetupError(
                    "invalid code", reason=Reason.SECOND_FACTOR_CODE_INVALID
                )
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
