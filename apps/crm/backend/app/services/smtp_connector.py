"""Коннектор «Почта» в «Подключениях» (M3-CRM-08, ADR-0018): настройки, секреты, «Проверить связь».

Как у ERP: несекретное — `settings.integrations.smtp`, логин и пароль — `integration_secrets`
(только на запись: в ответах `configured`, `last4`, `updated_at`), сохранение — после пароля
админа, аудит без значений. «Проверить связь» — соединение, EHLO, STARTTLS/SMTPS и AUTH без
отправки; «Тестовое письмо» — обычное письмо через журнал и очередь на адрес самого админа.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import (
    ConflictError,
    NotFoundError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.domain.smtp import Security, email_problem, host_problem, normalize_host
from app.integrations.smtp import SmtpCheck, SmtpErrorKind, SmtpProbeError, SmtpResolution, Source
from app.repositories import users as users_repo
from app.security import audit, reauth
from app.security.principal import Principal
from app.security.secrets_store import (
    SMTP_PASSWORD,
    SMTP_USERNAME,
    SecretsStore,
    SecretStatus,
    last4,
)
from app.services.mail import EmailLogView, MailService
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

SETTINGS_KEY: Final = "integrations"
_REASONS: Final[dict[SmtpErrorKind, Reason]] = {
    "invalid_host": Reason.SMTP_INVALID_HOST,
    "unavailable": Reason.SMTP_UNAVAILABLE,
    "auth_failed": Reason.SMTP_AUTH_FAILED,
    "tls_failed": Reason.SMTP_TLS_FAILED,
    "rejected": Reason.SMTP_REJECTED,
}


@dataclass(frozen=True, slots=True)
class SmtpStatus:
    """Состояние коннектора без значений секретов."""

    configured: bool
    host: str
    port: int
    security: Security
    from_email: str
    from_name: str
    settings_source: Source
    username: str
    username_source: Source
    password_configured: bool
    password_source: Source
    password_last4: str | None
    password_updated_at: datetime | None
    secrets_enabled: bool


class SmtpConnectorService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        store: SecretsStore,
        mail: MailService,
        *,
        lockout: reauth.LockoutPolicy | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._store = store
        self._mail = mail
        self._lockout = lockout or reauth.LockoutPolicy()

    async def resolution(self) -> SmtpResolution:
        return await self._mail.resolution()

    async def status(self) -> SmtpStatus:
        resolved = await self.resolution()
        password = await self._secret_status(SMTP_PASSWORD)
        return SmtpStatus(
            configured=resolved.connection is not None,
            host=resolved.host,
            port=resolved.port,
            security=resolved.security,
            from_email=resolved.from_email,
            from_name=resolved.from_name,
            settings_source=resolved.settings_source,
            # Логин — не секрет (виден админу), но хранится рядом с паролем в `integration_secrets`.
            username=resolved.username,
            username_source=resolved.username_source,
            password_configured=bool(resolved.password),
            password_source=resolved.password_source,
            password_last4=password.last4 if password else None,
            password_updated_at=password.updated_at if password else None,
            secrets_enabled=self._store.enabled,
        )

    async def _secret_status(self, key: str) -> SecretStatus | None:
        if not self._store.enabled:
            return None
        try:
            return await self._store.status(key)
        except Exception:
            logger.warning("smtp_secret_status_unavailable", key=key, exc_info=True)
            return None

    async def save(
        self,
        who: Principal,
        *,
        host: str,
        port: int,
        security: Security,
        from_email: str,
        from_name: str,
        username: str | None,
        password: str | None,
        admin_password: str,
    ) -> SmtpStatus:
        """Пароль админа → проверка полей → настройки в `settings`, секреты в хранилище → аудит.

        Пустой хост выключает коннектор (настройки из `.env`, если заданы, продолжают действовать).
        `None` вместо логина/пароля — оставить прежние; пустая строка логина — снять логин.
        """
        host = normalize_host(host)
        if host and (problem := host_problem(host)) is not None:
            raise ValidationFailedError(
                f"smtp host is invalid: {problem}", reason=Reason.SMTP_INVALID_HOST, field="host"
            )
        from_email = from_email.strip().lower()
        if host and (problem := email_problem(from_email)) is not None:
            raise ValidationFailedError(
                f"sender address is invalid: {problem}",
                reason=Reason.INVALID_EMAIL,
                field="from_email",
            )
        secrets = {SMTP_USERNAME: username, SMTP_PASSWORD: password}
        to_save = {key: value.strip() for key, value in secrets.items() if value is not None}
        if to_save and not self._store.enabled:
            raise ConflictError("SECRETS_KEY is not set", reason=Reason.SECRETS_KEY_MISSING)
        await self._reauth(who.user_id, admin_password)
        before = await self._audit_facts()
        current = (await self._settings.get()).integrations
        payload = current.model_dump(mode="json")
        payload["smtp"] = {
            "host": host,
            "port": port,
            "security": security,
            "from_email": from_email,
            "from_name": from_name.strip(),
        }
        await self._settings.update(SETTINGS_KEY, payload, who.user_id)
        async with self._sessions() as session, session.begin():
            for key, value in to_save.items():
                await self._store.put(session, key, value, who.user_id)
            after = {**before, **{f"smtp_{k}": v for k, v in payload["smtp"].items()}}
            if SMTP_USERNAME in to_save:
                after["smtp_username"] = to_save[SMTP_USERNAME]
            if SMTP_PASSWORD in to_save:
                after["smtp_password_last4"] = last4(to_save[SMTP_PASSWORD])
            await audit.record(
                session,
                who.actor,
                "integrations.smtp",
                "integration",
                "smtp",
                before=before,
                after=after,
            )
        logger.info("smtp_connector_saved", user_id=who.user_id, secrets=sorted(to_save))
        return await self.status()

    async def _audit_facts(self) -> dict[str, object]:
        """Что попадает в аудит: хост, порт, отправитель, логин и last4 пароля — не значения."""
        status = await self.status()
        return {
            "smtp_host": status.host,
            "smtp_port": status.port,
            "smtp_security": status.security,
            "smtp_from_email": status.from_email,
            "smtp_from_name": status.from_name,
            "smtp_username": status.username,
            "smtp_password_last4": status.password_last4,
        }

    async def _reauth(self, user_id: int, password: str) -> None:
        """Пароль с тем же lockout, что у входа; счётчик коммитится до ошибки (как у бота)."""
        async with self._sessions() as session, session.begin():
            user = await users_repo.get(session, user_id, for_update=True)
            if user is None:
                raise ValidationFailedError(
                    "password is wrong", reason=Reason.WRONG_PASSWORD, field="password"
                )
            failure = reauth.check(user, password, datetime.now(UTC), self._lockout)
        if failure is not None:
            raise failure

    async def check(self) -> SmtpCheck:
        """«Проверить связь»: соединение + EHLO + TLS + AUTH без отправки; ошибка — ADR-0017."""
        connection = (await self.resolution()).connection
        if connection is None:
            raise ConflictError(
                "smtp connector is not configured", reason=Reason.SMTP_NOT_CONFIGURED
            )
        try:
            return await self._mail.transport.check(connection)
        except SmtpProbeError as exc:
            logger.warning("smtp_check_failed", kind=exc.kind, detail=exc.detail)
            if exc.kind == "invalid_host":
                raise ValidationFailedError(
                    f"smtp host is invalid: {exc.detail}",
                    reason=Reason.SMTP_INVALID_HOST,
                    field="host",
                ) from exc
            raise UpstreamUnavailableError(
                f"smtp check failed: {exc.kind}", reason=_REASONS[exc.kind], detail=exc.detail
            ) from exc

    async def test_send(self, who: Principal) -> EmailLogView:
        """Тестовое письмо самому админу — через журнал и очередь, как настоящее."""
        async with self._sessions() as session:
            user = await users_repo.get(session, who.user_id)
        if user is None:
            raise NotFoundError("user not found")
        resolved = await self.resolution()
        return await self._mail.send(
            "test",
            user.email,
            {"full_name": user.full_name, "host": resolved.host, "from_email": resolved.from_email},
            user_id=user.id,
            requested_by=who.user_id,
        )
