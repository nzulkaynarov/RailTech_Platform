"""Приём почты в карточке «Почта» (W18A-P2, B-INB-5): настройки, секреты, «Проверить приём».

Как SMTP P1 (`smtp_connector.py`): несекретное — `settings.integrations.imap`, логин и пароль
приложения — `integration_secrets` (только на запись: в ответе «задан», `last4`, когда сменён),
сохранение — после пароля админа, аудит без значений. «Проверить приём» — вход и открытие папки
только на чтение; итог словом-кодом в ответе (без нового `Reason` в контракте).

Папки (W18A-P2-2): «Найти папки» — `LIST` ящика с подсказкой спам-папки (флаг `\\Junk`); в
настройке — список папок опроса с отметкой «спам»; итог опроса в ответе — сводка по папкам
(последняя ошибка любой папки видна админу).
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, Reason, ValidationFailedError
from app.domain.inbound_folders import (
    FolderSetting,
    decode_folder,
    primary_folder,
    resolve_folders,
    suggest_spam,
)
from app.domain.sender_auth import DEFAULT_TRUSTED
from app.domain.smtp import host_problem, normalize_host
from app.integrations.imap import ImapClient, ImapProbeError, ImapResolution, resolve_imap
from app.models.inbound_mail import InboundMailbox
from app.repositories import inbound_mail as repo
from app.repositories import users as users_repo
from app.schemas.inbound_mail import (
    ImapCheckOut,
    ImapFolderIn,
    ImapFolderOut,
    ImapFoldersOut,
    ImapServerFolder,
    ImapStatusOut,
)
from app.security import audit, reauth
from app.security.principal import Principal
from app.security.secrets_store import IMAP_PASSWORD, IMAP_USERNAME, SecretsStore, last4
from app.services.inbound_mail_history import view as history_view
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

SETTINGS_KEY = "integrations"


class ImapConnectorService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        store: SecretsStore,
        client: ImapClient,
        *,
        lockout: reauth.LockoutPolicy | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._store = store
        self._client = client
        self._lockout = lockout or reauth.LockoutPolicy()

    async def resolution(self) -> ImapResolution:
        return await resolve_imap(self._store, self._settings)

    async def configured(self) -> bool:
        return (await self.resolution()).connection is not None

    async def address(self) -> str | None:
        """Адрес самого общего ящика — логин приёма (его нет в «Ответить всем»)."""
        return (await self.resolution()).username.strip().lower() or None

    async def status(self) -> ImapStatusOut:
        resolved = await self.resolution()
        secret = None
        if self._store.enabled:
            try:
                secret = await self._store.status(IMAP_PASSWORD)
            except Exception:
                logger.warning("imap_secret_status_unavailable", exc_info=True)
        names = [f.name for f in resolved.folders]
        async with self._sessions() as session:
            state = summary(await repo.mailboxes(session, names))
            last_import = await repo.last_import(session)
        imap = (await self._settings.get()).integrations.imap
        return ImapStatusOut(
            configured=resolved.connection is not None,
            host=resolved.host,
            port=resolved.port,
            security=resolved.security,
            mailbox=resolved.mailbox,
            assist_enabled=imap.assist_enabled,
            personal_rule=imap.personal_rule,
            personal_label=imap.personal_label,
            trusted_auth_servers=list(imap.trusted_auth_servers),
            username=resolved.username,
            password_configured=bool(resolved.password),
            password_last4=secret.last4 if secret else None,
            password_updated_at=secret.updated_at if secret else None,
            secrets_enabled=self._store.enabled,
            last_poll_at=state.last_poll_at if state else None,
            last_ok_at=state.last_ok_at if state else None,
            last_error_kind=state.last_error_kind if state else None,
            last_error=state.last_error if state else None,
            folders=[
                ImapFolderOut(name=f.name, label=decode_folder(f.name), spam=f.spam)
                for f in resolved.folders
            ],
            history=history_view(last_import) if last_import is not None else None,
        )

    async def save(
        self,
        who: Principal,
        *,
        host: str,
        port: int,
        security: str,
        mailbox: str,
        assist_enabled: bool,
        personal_rule: bool = True,
        personal_label: str = "Адресовано лично",
        trusted_auth_servers: list[str] | None = None,
        username: str | None = None,
        password: str | None,
        admin_password: str,
        folders: list[ImapFolderIn] | None = None,
    ) -> ImapStatusOut:
        host = normalize_host(host.removeprefix("imap://").removeprefix("imaps://"))
        if host and (problem := host_problem(host)) is not None:
            raise ValidationFailedError(
                f"imap host is invalid: {problem}", reason=Reason.SMTP_INVALID_HOST, field="host"
            )
        secrets = {IMAP_USERNAME: username, IMAP_PASSWORD: password}
        to_save = {key: value.strip() for key, value in secrets.items() if value is not None}
        if to_save and not self._store.enabled:
            raise ConflictError("SECRETS_KEY is not set", reason=Reason.SECRETS_KEY_MISSING)
        await self._reauth(who.user_id, admin_password)
        before = await self.status()
        payload = (await self._settings.get()).integrations.model_dump(mode="json")
        kept: list[dict[str, object]] = payload["imap"].get("folders", [])
        primary = mailbox.strip() or "INBOX"
        if folders is not None:  # новый список папок; `mailbox` — первая не спам (совместимость)
            chosen = resolve_folders([FolderSetting(f.name, f.spam) for f in folders], primary)
            kept = [{"name": f.name, "spam": f.spam} for f in chosen]
            primary = primary_folder(chosen)
        payload["imap"] = {
            "host": host,
            "port": port,
            "security": security,
            "mailbox": primary,
            "folders": kept,
            "assist_enabled": assist_enabled,
            "personal_rule": personal_rule,
            "personal_label": personal_label.strip() or "Адресовано лично",
            "trusted_auth_servers": (
                trusted_auth_servers
                if trusted_auth_servers is not None
                else payload["imap"].get("trusted_auth_servers", list(DEFAULT_TRUSTED))
            ),
        }
        await self._settings.update(SETTINGS_KEY, payload, who.user_id)
        async with self._sessions() as session, session.begin():
            for key, value in to_save.items():
                await self._store.put(session, key, value, who.user_id)
            after = {f"imap_{k}": v for k, v in payload["imap"].items()}
            if IMAP_USERNAME in to_save:
                after["imap_username"] = to_save[IMAP_USERNAME]
            if IMAP_PASSWORD in to_save:
                after["imap_password_last4"] = last4(to_save[IMAP_PASSWORD])
            await audit.record(
                session,
                who.actor,
                "integrations.imap",
                "integration",
                "imap",
                before={
                    "imap_host": before.host,
                    "imap_port": before.port,
                    "imap_mailbox": before.mailbox,
                    "imap_username": before.username,
                    "imap_password_last4": before.password_last4,
                },
                after=after,
            )
        logger.info("imap_connector_saved", user_id=who.user_id, secrets=sorted(to_save))
        return await self.status()

    async def _reauth(self, user_id: int, password: str) -> None:
        async with self._sessions() as session, session.begin():
            user = await users_repo.get(session, user_id, for_update=True)
            if user is None:
                raise ValidationFailedError(
                    "password is wrong", reason=Reason.WRONG_PASSWORD, field="password"
                )
            failure = reauth.check(user, password, datetime.now(UTC), self._lockout)
        if failure is not None:
            raise failure

    async def check(self) -> ImapCheckOut:
        connection = (await self.resolution()).connection
        if connection is None:
            return ImapCheckOut(ok=False, error_kind="not_configured")
        try:
            result = await self._client.check(connection)
        except ImapProbeError as exc:
            logger.warning("imap_check_failed", kind=exc.kind, detail=exc.detail)
            return ImapCheckOut(ok=False, error_kind=exc.kind, detail=exc.detail or None)
        return ImapCheckOut(ok=True, messages=result.messages, latency_ms=result.latency_ms)

    async def folders(self) -> ImapFoldersOut:
        """«Найти папки»: папки ящика (`LIST`) и подсказка спам-папки; итог — в ответе."""
        connection = (await self.resolution()).connection
        if connection is None:
            return ImapFoldersOut(ok=False, error_kind="not_configured")
        try:
            found = await self._client.folders(connection)
        except ImapProbeError as exc:
            logger.warning("imap_folders_failed", kind=exc.kind, detail=exc.detail)
            return ImapFoldersOut(ok=False, error_kind=exc.kind, detail=exc.detail or None)
        return ImapFoldersOut(
            ok=True,
            folders=[
                ImapServerFolder(name=f.name, label=f.label, junk=f.junk, selectable=f.selectable)
                for f in found
            ],
            spam_suggestion=suggest_spam(found),
        )


def summary(states: list[InboundMailbox]) -> InboundMailbox | None:
    """Итог опроса по папкам: последний опрос и успех — самые свежие, ошибка — любой папки."""
    if not states:
        return None
    failed = [s for s in states if s.last_error_kind]
    polls = [s.last_poll_at for s in states if s.last_poll_at]
    oks = [s.last_ok_at for s in states if s.last_ok_at]
    return InboundMailbox(
        mailbox=states[0].mailbox,
        last_poll_at=max(polls) if polls else None,
        last_ok_at=max(oks) if oks else None,
        last_error_kind=failed[0].last_error_kind if failed else None,
        last_error=failed[0].last_error if failed else None,
    )
