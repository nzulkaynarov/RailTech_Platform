"""Коннектор «ERP» в «Подключениях» (M3-CRM-02, ADR-0018): адрес, секреты, «Проверить связь».

Безопасность — как у токена бота: секреты только на запись (в ответы уходят `configured`,
`last4`, `updated_at`), сохранение — после пароля админа, аудит без значений. Здоровье ERP
для «Состояния системы» кэшируется на 30 с, чтобы страница не дёргала ERP при каждом рендере;
«Проверить связь» всегда идёт в ERP и обновляет кэш.
"""

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.backoffice import BackofficeMode, backoffice_mode
from app.domain.erp_connector import base_url_problem, normalize_base_url
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError, ValidationFailedError
from app.domain.system_status import ErpFacts
from app.integrations.erp import (
    ErpErrorKind,
    ErpHealth,
    ErpProbe,
    ErpProbeError,
    ErpResolution,
    Source,
    resolve_erp,
)
from app.repositories import users as users_repo
from app.security import audit, reauth
from app.security.principal import Principal
from app.security.secrets_store import (
    ERP_SERVICE_TOKEN,
    ERP_WEBHOOK_SECRET,
    ERP_WEBHOOK_SECRET_PREVIOUS,
    SecretsStore,
    SecretStatus,
    last4,
)
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

SETTINGS_KEY: Final = "integrations"
HEALTH_CACHE_TTL_S: Final = 30.0
_REASONS: Final[dict[ErpErrorKind, Reason]] = {
    "invalid_url": Reason.ERP_INVALID_URL,
    "unauthorized": Reason.ERP_UNAUTHORIZED,
    "unavailable": Reason.ERP_UNAVAILABLE,
    "bad_response": Reason.ERP_BAD_RESPONSE,
}


@dataclass(frozen=True, slots=True)
class ErpStatus:
    """Состояние коннектора без значений секретов."""

    configured: bool
    mode: BackofficeMode
    base_url: str
    base_url_source: Source
    token_configured: bool
    token_source: Source
    token_last4: str | None
    token_updated_at: datetime | None
    webhook_secret_configured: bool
    webhook_secret_source: Source
    webhook_secret_last4: str | None
    webhook_secret_updated_at: datetime | None
    webhook_secret_previous_configured: bool
    webhook_secret_previous_source: Source
    webhook_secret_previous_last4: str | None
    webhook_secret_previous_updated_at: datetime | None
    secrets_enabled: bool


@dataclass(frozen=True, slots=True)
class _CachedHealth:
    facts: ErpFacts
    at: float


class ErpConnectorService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        store: SecretsStore,
        config: Settings,
        probe: ErpProbe,
        *,
        lockout: reauth.LockoutPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        cache_ttl_s: float = HEALTH_CACHE_TTL_S,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._store = store
        self._config = config
        self._probe = probe
        self._lockout = lockout or reauth.LockoutPolicy()
        self._clock = clock
        self._ttl = cache_ttl_s
        self._cached: _CachedHealth | None = None

    async def resolution(self) -> ErpResolution:
        return await resolve_erp(self._store, self._config, self._settings)

    async def mode(self) -> BackofficeMode:
        """Провайдер режима для `ClientService` (ADR-0022): коннектор настроен → `erp`."""
        resolved = await self.resolution()
        return backoffice_mode(erp_connector_configured=resolved.connection is not None)

    async def status(self) -> ErpStatus:
        resolved = await self.resolution()
        token = await self._secret_status(ERP_SERVICE_TOKEN)
        webhook = await self._secret_status(ERP_WEBHOOK_SECRET)
        previous = await self._secret_status(ERP_WEBHOOK_SECRET_PREVIOUS)
        return ErpStatus(
            configured=resolved.connection is not None,
            mode=backoffice_mode(erp_connector_configured=resolved.connection is not None),
            base_url=resolved.base_url,
            base_url_source=resolved.base_url_source,
            token_configured=bool(resolved.token),
            token_source=resolved.token_source,
            token_last4=token.last4 if token else None,
            token_updated_at=token.updated_at if token else None,
            webhook_secret_configured=bool(resolved.webhook_secret),
            webhook_secret_source=resolved.webhook_secret_source,
            webhook_secret_last4=webhook.last4 if webhook else None,
            webhook_secret_updated_at=webhook.updated_at if webhook else None,
            webhook_secret_previous_configured=bool(resolved.webhook_secret_previous),
            webhook_secret_previous_source=resolved.webhook_secret_previous_source,
            webhook_secret_previous_last4=previous.last4 if previous else None,
            webhook_secret_previous_updated_at=previous.updated_at if previous else None,
            secrets_enabled=self._store.enabled,
        )

    async def _secret_status(self, key: str) -> SecretStatus | None:
        if not self._store.enabled:
            return None
        try:
            return await self._store.status(key)
        except Exception:
            logger.warning("erp_secret_status_unavailable", key=key, exc_info=True)
            return None

    async def save(
        self,
        who: Principal,
        *,
        base_url: str,
        service_token: str | None,
        webhook_secret: str | None,
        password: str,
        webhook_secret_previous: str | None = None,
        clear_webhook_secret_previous: bool = False,
    ) -> ErpStatus:
        """Пароль → проверка адреса → адрес в `settings`, секреты в хранилище → аудит без значений.

        Пустой адрес выключает коннектор (адрес из `.env`, если задан, продолжает действовать).
        `None` вместо секрета — оставить прежний; пустую строку схема не пропускает.

        Ротация секрета вебхуков без простоя (FIX-35): `webhook_secret` — текущий (им подписывает
        ERP), `webhook_secret_previous` — предыдущий, его CRM принимает наравне с текущим, пока
        админ не снимет (`clear_webhook_secret_previous=True`). Ни перезапуска, ни `.env`.
        """
        url = normalize_base_url(base_url)
        if url and (problem := base_url_problem(url)) is not None:
            raise ValidationFailedError(
                f"erp base url is invalid: {problem}",
                reason=Reason.ERP_INVALID_URL,
                field="base_url",
            )
        secrets = {
            ERP_SERVICE_TOKEN: service_token,
            ERP_WEBHOOK_SECRET: webhook_secret,
            ERP_WEBHOOK_SECRET_PREVIOUS: webhook_secret_previous,
        }
        to_save = {key: value.strip() for key, value in secrets.items() if value is not None}
        clear_previous = clear_webhook_secret_previous and not to_save.get(
            ERP_WEBHOOK_SECRET_PREVIOUS
        )
        to_clear = [ERP_WEBHOOK_SECRET_PREVIOUS] if clear_previous else []
        if (to_save or to_clear) and not self._store.enabled:
            raise ConflictError("SECRETS_KEY is not set", reason=Reason.SECRETS_KEY_MISSING)
        await self._reauth(who.user_id, password)
        before = await self._audit_facts()
        await self._settings.update(SETTINGS_KEY, {"erp_base_url": url}, who.user_id)
        async with self._sessions() as session, session.begin():
            for key, value in to_save.items():
                await self._store.put(session, key, value, who.user_id)
            for key in to_clear:
                await self._store.delete(session, key)
            after = {**before, "base_url": url}
            for key, value in to_save.items():
                after[f"{key}_last4"] = last4(value)
            for key in to_clear:
                after[f"{key}_last4"] = None
            await audit.record(
                session,
                who.actor,
                "integrations.erp",
                "integration",
                "erp",
                before=before,
                after=after,
            )
        self._cached = None
        logger.info(
            "erp_connector_saved",
            user_id=who.user_id,
            secrets=sorted(to_save),
            cleared=sorted(to_clear),
        )
        return await self.status()

    async def _audit_facts(self) -> dict[str, object]:
        """Что попадает в аудит: адрес и последние 4 символа секретов — никогда сами значения."""
        status = await self.status()
        return {
            "base_url": status.base_url,
            f"{ERP_SERVICE_TOKEN}_last4": status.token_last4,
            f"{ERP_WEBHOOK_SECRET}_last4": status.webhook_secret_last4,
            f"{ERP_WEBHOOK_SECRET_PREVIOUS}_last4": status.webhook_secret_previous_last4,
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

    async def check(self) -> ErpHealth:
        """«Проверить связь»: всегда в ERP; ошибка — доменная с подкодом ADR-0017; кэш обновлён."""
        connection = (await self.resolution()).connection
        if connection is None:
            raise ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)
        try:
            health = await self._probe.health(connection)
        except ErpProbeError as exc:
            self._remember(ErpFacts(configured=True, error=exc.kind, detail=exc.detail))
            logger.warning("erp_health_failed", kind=exc.kind, detail=exc.detail)
            if exc.kind == "invalid_url":
                raise ValidationFailedError(
                    f"erp base url is invalid: {exc.detail}",
                    reason=Reason.ERP_INVALID_URL,
                    field="base_url",
                ) from exc
            raise UpstreamUnavailableError(
                f"erp health check failed: {exc.kind}", reason=_REASONS[exc.kind]
            ) from exc
        self._remember(_facts(health))
        return health

    async def health_facts(self) -> ErpFacts:
        """Для «Состояния системы»: не бросает, кэш 30 с; без коннектора — «не настроен»."""
        cached = self._cached
        if cached is not None and self._clock() - cached.at < self._ttl:
            return cached.facts
        if (await self.resolution()).connection is None:
            facts = ErpFacts(configured=False)
            self._remember(facts)
            return facts
        with contextlib.suppress(UpstreamUnavailableError, ValidationFailedError):
            await self.check()
        return self._cached.facts if self._cached is not None else ErpFacts(configured=True)

    def _remember(self, facts: ErpFacts) -> None:
        self._cached = _CachedHealth(facts, self._clock())


def _facts(health: ErpHealth) -> ErpFacts:
    return ErpFacts(
        configured=True,
        status=health.status,
        version=health.version,
        migrations_applied=health.migrations_applied,
        queue_alive=health.queue_alive,
        checked_at=health.checked_at,
        latency_ms=health.latency_ms,
    )
