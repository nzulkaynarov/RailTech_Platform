"""Внешняя копия бэкапов в интерфейсе (OPS-GDRIVE-2, OPS-YADISK): провайдер, доступ, «Проверить».

Два провайдера, выбор — в той же форме (решение владельца 2026-10-31):

- **Яндекс Диск** компании (рекомендуется): логин Яндекс 360, путь папки на Диске и пароль
  приложения
  типа «Файлы» (WebDAV). Пароль — `integration_secrets` (`offsite_yandex_password`, только на
  запись,
  без последних символов); несекретное — `settings.integrations.offsite_yandex`.
- **Google Drive** (общий диск Workspace): JSON-ключ сервисного аккаунта и ID папки общего диска.
  Ключ — `offsite_gdrive_key` (в ответах — адрес аккаунта и последние 4 символа ID ключа);
  несекретное — `settings.integrations.offsite_gdrive`. На личном Google ключ не работает:
  у сервисного аккаунта нет своего места (`storageQuotaExceeded`, прод 2026-10-29).

Выбор — `settings.integrations.offsite_provider`; не выбран — настроенный Google Drive остаётся
Google Drive (без миграции данных), иначе по умолчанию Яндекс Диск.

Сохранение — после пароля админа, в журнал действий — без значений. Доставка сервису копирования
`offsite-backup` — через бакет `offsite-config` RustFS: у ключа CRM там только запись (`PutObject`),
у
`offsite` — только чтение (infra/s3/init.sh). Объекты: `settings.json` (провайдер и несекретное),
`gdrive-sa.json` (ключ Google) или `yandex-password` (пароль приложения). Сервис забирает их сам раз
в
минуту. Сначала доставка, потом сохранение: не дошло — ничего не сохранено, админ видит ошибку.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain import gdrive, yadisk
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError, ValidationFailedError
from app.repositories import users as users_repo
from app.schemas.settings import IntegrationsSettings
from app.security import audit, reauth
from app.security.principal import Principal
from app.security.secrets_store import OFFSITE_GDRIVE_KEY, OFFSITE_YANDEX_PASSWORD, SecretsStore
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

SETTINGS_KEY: Final = "integrations"
KEY_OBJECT: Final = "gdrive-sa.json"
YANDEX_PASSWORD_OBJECT: Final = "yandex-password"  # noqa: S105 — имя объекта, не секрет
SETTINGS_OBJECT: Final = "settings.json"

Provider = Literal["gdrive", "yandex"]
ProbeResult = gdrive.ProbeResult | yadisk.ProbeResult
Probe = Callable[[gdrive.ServiceAccountKey, str], Awaitable[gdrive.ProbeResult]]
YandexProbe = Callable[[str, str, str], Awaitable[yadisk.ProbeResult]]


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
    """Что видит админ: ни ключа, ни пароля — только адрес аккаунта или логин и признак «задан»."""

    provider: Provider
    configured: bool
    folder_id: str
    client_email: str
    key_suffix: str | None
    key_updated_at: datetime | None
    login: str
    folder_path: str
    app_password_configured: bool
    app_password_updated_at: datetime | None
    default_folder_path: str
    delivered_at: datetime | None
    last_check: OffsiteCheck | None
    secrets_enabled: bool


def provider_of(current: IntegrationsSettings) -> Provider:
    """Выбранный провайдер; не выбирали — Google Drive, если он уже настроен, иначе Яндекс Диск."""
    if current.offsite_provider is not None:
        return current.offsite_provider
    return "gdrive" if current.offsite_gdrive.folder_id else "yandex"


class OffsiteConnectorService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        store: SecretsStore,
        storage: Writer,
        bucket: str,
        probe: Probe,
        yandex_probe: YandexProbe,
        *,
        env: str = "prod",
        lockout: reauth.LockoutPolicy | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._store = store
        self._storage = storage
        self._bucket = bucket
        self._probe = probe
        self._yandex_probe = yandex_probe
        self._default_folder = yadisk.default_folder(env)
        self._lockout = lockout or reauth.LockoutPolicy()

    async def status(self) -> OffsiteStatus:
        current = (await self._settings.get()).integrations
        provider = provider_of(current)
        g, y = current.offsite_gdrive, current.offsite_yandex
        enabled = self._store.enabled
        key = await self._store.status(OFFSITE_GDRIVE_KEY) if enabled else None
        password = await self._store.status(OFFSITE_YANDEX_PASSWORD) if enabled else None
        if provider == "gdrive":
            configured = key is not None and bool(g.folder_id)
            delivered, check = g.delivered_at, g.last_check
        else:
            configured = password is not None and bool(y.login) and bool(y.folder_path)
            delivered, check = y.delivered_at, y.last_check
        return OffsiteStatus(
            provider=provider,
            configured=configured,
            folder_id=g.folder_id,
            client_email=g.client_email if key is not None else "",
            key_suffix=g.key_suffix or None if key is not None else None,
            key_updated_at=key.updated_at if key is not None else None,
            login=y.login,
            folder_path=y.folder_path,
            app_password_configured=password is not None,
            app_password_updated_at=password.updated_at if password is not None else None,
            default_folder_path=self._default_folder,
            delivered_at=delivered,
            last_check=(
                OffsiteCheck(
                    check.reason == "ok", check.reason, check.folder_name, check.checked_at
                )
                if check is not None
                else None
            ),
            secrets_enabled=enabled,
        )

    async def save(
        self,
        who: Principal,
        *,
        provider: Provider = "gdrive",
        key_json: str | None = None,
        folder_id: str = "",
        login: str = "",
        folder_path: str = "",
        app_password: str | None = None,
        admin_password: str,
    ) -> OffsiteStatus:
        """Поля → пароль админа → доставка в `offsite-config` → проверка → секрет, настройки, аудит.

        Секрет `None` (ключ Google или пароль приложения) — оставить прежний."""
        if provider == "yandex":
            return await self._save_yandex(who, login, folder_path, app_password, admin_password)
        return await self._save_gdrive(who, key_json, folder_id, admin_password)

    async def _save_gdrive(
        self, who: Principal, key_json: str | None, folder_id: str, admin_password: str
    ) -> OffsiteStatus:
        folder = gdrive.normalize_folder_id(folder_id)
        if folder is None:
            raise ValidationFailedError(
                "folder id is invalid", reason=Reason.OFFSITE_FOLDER_INVALID, field="folder_id"
            )
        self._require_secrets()
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
        await self._deliver(
            (KEY_OBJECT, raw.encode(), "application/json"),
            {"provider": "gdrive", "folder_id": folder},
        )
        now = datetime.now(UTC)
        result = await self._probe(key, folder)
        current = (await self._settings.get()).integrations
        payload = current.model_dump(mode="json")
        payload["offsite_provider"] = "gdrive"
        payload["offsite_gdrive"] = {
            "folder_id": folder,
            "client_email": key.client_email,
            "key_suffix": gdrive.key_suffix(key.private_key_id),
            "delivered_at": now.isoformat(),
            "last_check": _check_payload(result, now),
        }
        after = {
            "provider": "gdrive",
            "folder_id": folder,
            "client_email": key.client_email,
            "key_suffix": gdrive.key_suffix(key.private_key_id),
            "key_changed": key_json is not None,
        }
        secret = (OFFSITE_GDRIVE_KEY, raw, True) if key_json is not None else None
        await self._persist(who, payload, secret, "integrations.offsite_gdrive", before, after)
        logger.info("offsite_gdrive_saved", user_id=who.user_id, check=result.reason)
        return await self.status()

    async def _save_yandex(
        self,
        who: Principal,
        login: str,
        folder_path: str,
        app_password: str | None,
        admin_password: str,
    ) -> OffsiteStatus:
        account = yadisk.normalize_login(login)
        if account is None:
            raise ValidationFailedError(
                "login is not an email", reason=Reason.OFFSITE_LOGIN_INVALID, field="login"
            )
        folder = yadisk.normalize_folder(folder_path or self._default_folder)
        if folder is None:
            raise ValidationFailedError(
                "folder path is invalid",
                reason=Reason.OFFSITE_FOLDER_INVALID,
                field="folder_path",
            )
        self._require_secrets()
        given = yadisk.normalize_password(app_password) if app_password is not None else None
        secret = given or await self._store.get(OFFSITE_YANDEX_PASSWORD)
        if not secret or len(secret) > yadisk.PASSWORD_MAX:
            raise ValidationFailedError(
                "app password is required",
                reason=Reason.OFFSITE_APP_PASSWORD_INVALID,
                field="app_password",
            )
        await self._reauth(who.user_id, admin_password)
        before = await self._audit_facts()
        await self._deliver(
            (YANDEX_PASSWORD_OBJECT, secret.encode(), "text/plain"),
            {"provider": "yandex", "login": account, "folder_path": folder},
        )
        now = datetime.now(UTC)
        result = await self._yandex_probe(account, secret, folder)
        current = (await self._settings.get()).integrations
        payload = current.model_dump(mode="json")
        payload["offsite_provider"] = "yandex"
        payload["offsite_yandex"] = {
            "login": account,
            "folder_path": folder,
            "delivered_at": now.isoformat(),
            "last_check": _check_payload(result, now),
        }
        after = {
            "provider": "yandex",
            "login": account,
            "folder_path": folder,
            "password_changed": bool(given),
        }
        stored = (OFFSITE_YANDEX_PASSWORD, secret, False) if given else None
        await self._persist(who, payload, stored, "integrations.offsite_yandex", before, after)
        logger.info("offsite_yandex_saved", user_id=who.user_id, check=result.reason)
        return await self.status()

    async def check(self, who: Principal) -> OffsiteCheck:
        """«Проверить»: секрет из хранилища и сохранённая папка выбранного провайдера; итог
        запоминается в настройках провайдера."""
        current = (await self._settings.get()).integrations
        payload = current.model_dump(mode="json")
        now = datetime.now(UTC)
        result: ProbeResult
        if provider_of(current) == "gdrive":
            folder = current.offsite_gdrive.folder_id
            raw = await self._store.get(OFFSITE_GDRIVE_KEY) if self._store.enabled else None
            key = gdrive.parse_key(raw) if raw is not None else None
            if key is None or isinstance(key, str) or not folder:
                raise ConflictError(
                    "offsite copy is not configured", reason=Reason.OFFSITE_NOT_CONFIGURED
                )
            result = await self._probe(key, folder)
            payload["offsite_gdrive"]["last_check"] = _check_payload(result, now)
        else:
            y = current.offsite_yandex
            secret = await self._store.get(OFFSITE_YANDEX_PASSWORD) if self._store.enabled else None
            if not secret or not y.login or not y.folder_path:
                raise ConflictError(
                    "offsite copy is not configured", reason=Reason.OFFSITE_NOT_CONFIGURED
                )
            result = await self._yandex_probe(y.login, secret, y.folder_path)
            payload["offsite_yandex"]["last_check"] = _check_payload(result, now)
        await self._settings.update(SETTINGS_KEY, payload, who.user_id)
        logger.info("offsite_checked", reason=result.reason, detail=result.detail)
        return OffsiteCheck(result.ok, result.reason, result.folder_name, now)

    def _require_secrets(self) -> None:
        if not self._store.enabled:
            raise ConflictError("SECRETS_KEY is not set", reason=Reason.SECRETS_KEY_MISSING)

    async def _deliver(self, secret: tuple[str, bytes, str], settings: dict[str, str]) -> None:
        """Секрет и настройка — в `offsite-config` для offsite-backup (у CRM там только запись).
        Секрет — раньше: сервис перечитывает настройку, когда меняется любой из объектов."""
        name, data, content_type = secret
        # Кириллица пути — как есть: сервис читает JSON строкой sed, без разбора
        # \\u-последовательностей.
        body = json.dumps(settings, ensure_ascii=False).encode()
        try:
            await self._storage.put(self._bucket, name, data, content_type)
            await self._storage.put(self._bucket, SETTINGS_OBJECT, body, "application/json")
        except Exception as exc:
            logger.warning("offsite_delivery_failed", error=type(exc).__name__)
            raise UpstreamUnavailableError(
                "offsite config delivery failed",
                reason=Reason.OFFSITE_DELIVERY_FAILED,
                detail=type(exc).__name__,
            ) from exc

    async def _persist(
        self,
        who: Principal,
        payload: dict[str, object],
        secret: tuple[str, str, bool] | None,
        action: str,
        before: dict[str, object],
        after: dict[str, object],
    ) -> None:
        """Секрет, настройки и аудит — одной транзакцией: секрет и папка не разъедутся при сбое."""
        async with self._sessions() as session, session.begin():
            if secret is not None:
                name, value, keep_last4 = secret
                put = self._store.put if keep_last4 else self._store.put_unmasked
                await put(session, name, value, who.user_id)
            await self._settings.update_in(session, SETTINGS_KEY, payload, who.user_id)
            await audit.record(
                session,
                who.actor,
                action,
                "integration",
                action.removeprefix("integrations."),
                before=before,
                after=after,
            )
        self._settings.invalidate()

    async def _audit_facts(self) -> dict[str, object]:
        status = await self.status()
        return {
            "provider": status.provider,
            "folder_id": status.folder_id,
            "client_email": status.client_email,
            "key_suffix": status.key_suffix,
            "login": status.login,
            "folder_path": status.folder_path,
            "app_password_configured": status.app_password_configured,
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


def _check_payload(result: ProbeResult, now: datetime) -> dict[str, object]:
    return {
        "reason": result.reason,
        "folder_name": result.folder_name,
        "checked_at": now.isoformat(),
    }
