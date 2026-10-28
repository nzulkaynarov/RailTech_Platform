"""Внешняя копия бэкапов в интерфейсе (OPS-GDRIVE-2): ключ, папка, «Проверить», доставка.

Владелец (через администратора Платформы) загружает JSON-ключ сервисного аккаунта Google и ID
папки общего диска, без захода на сервер.

- Ключ хранится зашифрованным в `integration_secrets` (`offsite_gdrive_key`, только на запись): в
  ответах — адрес аккаунта и последние 4 символа ID ключа. Несекретное — `settings.integrations.
  offsite_gdrive`. Сохранение — после пароля админа, в журнал действий — без значений.
- Доставка сервису копирования `offsite-backup` — через бакет `offsite-config` RustFS: у ключа CRM
  там только запись (`PutObject`), у `offsite` — только чтение (infra/s3/init.sh). Сервис забирает
  объекты сам раз в минуту; ни ручного шага на сервере, ни нового входа в CRM по сети. Сначала
  доставка, потом сохранение: не дошло — ничего не сохранено, админ видит ошибку.
- «Проверить» — запрос к Google ключом из хранилища: токен, папка, общий ли диск, можно ли писать.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import gdrive
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError, ValidationFailedError
from app.repositories import users as users_repo
from app.security import audit, reauth
from app.security.principal import Principal
from app.security.secrets_store import OFFSITE_GDRIVE_KEY, SecretsStore
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

SETTINGS_KEY: Final = "integrations"
KEY_OBJECT: Final = "gdrive-sa.json"
SETTINGS_OBJECT: Final = "settings.json"

Probe = Callable[[gdrive.ServiceAccountKey, str], Awaitable[gdrive.ProbeResult]]


class Writer(Protocol):
    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...


@dataclass(frozen=True, slots=True)
class OffsiteCheck:
    ok: bool
    reason: str
    folder_name: str | None
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class OffsiteStatus:
    """Что видит админ: без ключа — только адрес аккаунта и последние символы ID ключа."""

    configured: bool
    folder_id: str
    client_email: str
    key_suffix: str | None
    key_updated_at: datetime | None
    delivered_at: datetime | None
    last_check: OffsiteCheck | None
    secrets_enabled: bool


class OffsiteConnectorService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        store: SecretsStore,
        storage: Writer,
        bucket: str,
        probe: Probe,
        *,
        lockout: reauth.LockoutPolicy | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._store = store
        self._storage = storage
        self._bucket = bucket
        self._probe = probe
        self._lockout = lockout or reauth.LockoutPolicy()

    async def status(self) -> OffsiteStatus:
        current = (await self._settings.get()).integrations.offsite_gdrive
        secret = await self._store.status(OFFSITE_GDRIVE_KEY) if self._store.enabled else None
        check = current.last_check
        return OffsiteStatus(
            configured=secret is not None and bool(current.folder_id),
            folder_id=current.folder_id,
            client_email=current.client_email if secret is not None else "",
            key_suffix=current.key_suffix or None if secret is not None else None,
            key_updated_at=secret.updated_at if secret is not None else None,
            delivered_at=current.delivered_at,
            last_check=(
                OffsiteCheck(
                    check.reason == "ok", check.reason, check.folder_name, check.checked_at
                )
                if check is not None
                else None
            ),
            secrets_enabled=self._store.enabled,
        )

    async def save(
        self, who: Principal, *, key_json: str | None, folder_id: str, admin_password: str
    ) -> OffsiteStatus:
        """Поля → пароль админа → доставка в `offsite-config` → проверка у Google → секрет,
        настройки и аудит. `key_json = None` — оставить прежний ключ (сменить только папку)."""
        folder = gdrive.normalize_folder_id(folder_id)
        if folder is None:
            raise ValidationFailedError(
                "folder id is invalid", reason=Reason.OFFSITE_FOLDER_INVALID, field="folder_id"
            )
        if not self._store.enabled:
            raise ConflictError("SECRETS_KEY is not set", reason=Reason.SECRETS_KEY_MISSING)
        raw = (
            key_json.strip() if key_json is not None else await self._store.get(OFFSITE_GDRIVE_KEY)
        )
        if raw is None:
            raise ValidationFailedError(
                "service account key is required",
                reason=Reason.OFFSITE_KEY_INVALID,
                field="key_json",
            )
        key = gdrive.parse_key(raw)
        if isinstance(key, str):
            raise ValidationFailedError(
                f"service account key is invalid: {key}",
                reason=Reason.OFFSITE_KEY_INVALID,
                field="key_json",
                problem=key,
            )
        await self._reauth(who.user_id, admin_password)
        before = await self._audit_facts()
        await self._deliver(raw, folder)
        now = datetime.now(UTC)
        result = await self._probe(key, folder)
        current = (await self._settings.get()).integrations
        payload = current.model_dump(mode="json")
        payload["offsite_gdrive"] = {
            "folder_id": folder,
            "client_email": key.client_email,
            "key_suffix": gdrive.key_suffix(key.private_key_id),
            "delivered_at": now.isoformat(),
            "last_check": _check_payload(result, now),
        }
        # Секрет, настройки и аудит — одной транзакцией: ключ и папка не разъедутся при сбое.
        async with self._sessions() as session, session.begin():
            if key_json is not None:
                await self._store.put(session, OFFSITE_GDRIVE_KEY, raw, who.user_id)
            await self._settings.update_in(session, SETTINGS_KEY, payload, who.user_id)
            after = {
                "folder_id": folder,
                "client_email": key.client_email,
                "key_suffix": gdrive.key_suffix(key.private_key_id),
                "key_changed": key_json is not None,
            }
            await audit.record(
                session,
                who.actor,
                "integrations.offsite_gdrive",
                "integration",
                "offsite_gdrive",
                before=before,
                after=after,
            )
        self._settings.invalidate()
        logger.info("offsite_gdrive_saved", user_id=who.user_id, check=result.reason)
        return await self.status()

    async def check(self, who: Principal) -> OffsiteCheck:
        """«Проверить»: ключ из хранилища и сохранённая папка → Google; итог запоминается."""
        current = (await self._settings.get()).integrations
        folder = current.offsite_gdrive.folder_id
        raw = await self._store.get(OFFSITE_GDRIVE_KEY) if self._store.enabled else None
        key = gdrive.parse_key(raw) if raw is not None else None
        if key is None or isinstance(key, str) or not folder:
            raise ConflictError(
                "offsite copy is not configured", reason=Reason.OFFSITE_NOT_CONFIGURED
            )
        result = await self._probe(key, folder)
        now = datetime.now(UTC)
        payload = current.model_dump(mode="json")
        payload["offsite_gdrive"]["last_check"] = _check_payload(result, now)
        await self._settings.update(SETTINGS_KEY, payload, who.user_id)
        logger.info("offsite_gdrive_checked", reason=result.reason, detail=result.detail)
        return OffsiteCheck(result.ok, result.reason, result.folder_name, now)

    async def _deliver(self, raw: str, folder: str) -> None:
        """Ключ и папка — в `offsite-config` для offsite-backup (у CRM там только запись)."""
        body = json.dumps({"folder_id": folder}).encode()
        try:
            await self._storage.put(self._bucket, KEY_OBJECT, raw.encode(), "application/json")
            await self._storage.put(self._bucket, SETTINGS_OBJECT, body, "application/json")
        except Exception as exc:
            logger.warning("offsite_gdrive_delivery_failed", error=type(exc).__name__)
            raise UpstreamUnavailableError(
                "offsite config delivery failed",
                reason=Reason.OFFSITE_DELIVERY_FAILED,
                detail=type(exc).__name__,
            ) from exc

    async def _audit_facts(self) -> dict[str, object]:
        status = await self.status()
        return {
            "folder_id": status.folder_id,
            "client_email": status.client_email,
            "key_suffix": status.key_suffix,
        }

    async def _reauth(self, user_id: int, password: str) -> None:
        """Пароль с тем же lockout, что у входа; счётчик коммитится до ошибки (как у «Почты»)."""
        async with self._sessions() as session, session.begin():
            user = await users_repo.get(session, user_id, for_update=True)
            if user is None:
                raise ValidationFailedError(
                    "password is wrong", reason=Reason.WRONG_PASSWORD, field="password"
                )
            failure = reauth.check(user, password, datetime.now(UTC), self._lockout)
        if failure is not None:
            raise failure


def _check_payload(result: gdrive.ProbeResult, now: datetime) -> dict[str, object]:
    return {
        "reason": result.reason,
        "folder_name": result.folder_name,
        "checked_at": now.isoformat(),
    }
