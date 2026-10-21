"""Сопряжение CRM ↔ ERP в один клик (M3-CRM-10, ORCHESTRATOR §3.13, CONTRACTS §2).

«Подключить ERP»: админ вводит адрес ERP и одноразовый код из её настроек; CRM САМА генерирует
токен CRM→ERP, токен ERP→CRM и секрет вебхуков, передаёт их ERP вызовом `POST /pairing/accept`
(аутентификация — код) и только после успеха сохраняет у себя (шифрованно, `integration_secrets`)
и сразу делает «Проверить связь».

«Обновить ключи»: новая тройка под действующим токеном (`POST /pairing/rotate`). ERP держит два
токена CRM→ERP на переходный срок. CRM заранее принимает оба секрета вебхуков (новый текущий,
прежний предыдущий), поэтому события, подписанные в момент переключения ERP, не теряются; при
отказе ERP прежние значения возвращаются. Предыдущий секрет CRM снимает сама по истечении срока
перехода (`ErpConnectorService.expire_previous_secret`).

Безопасность: сохранение и ротация — только после пароля админа; сгенерированные значения, код и
токены не пишутся ни в журналы, ни в аудит (в аудите — адрес и последние 4 символа); без
`SECRETS_KEY` сопрягаться нельзя (секрет некуда положить зашифрованным) — это проверяется до
обращения к ERP.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.erp_connector import base_url_problem, normalize_base_url
from app.domain.errors import (
    ConflictError,
    DomainError,
    Reason,
    ValidationFailedError,
)
from app.integrations.erp import ErpHealth
from app.integrations.erp_pairing import ErpPairingClient, PairingSecrets
from app.security import audit
from app.security.principal import Principal
from app.security.secrets_store import (
    ERP_INBOUND_TOKEN,
    ERP_SERVICE_TOKEN,
    ERP_WEBHOOK_SECRET,
    ERP_WEBHOOK_SECRET_PREVIOUS,
    SecretsStore,
    last4,
)
from app.services.erp_connector import SETTINGS_KEY, ErpConnectorService, ErpStatus
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

# Сколько CRM ещё принимает предыдущий секрет вебхуков после «Обновить ключи»: как переходный срок
# токена в ERP.
DEFAULT_ROTATION_GRACE_S: Final = 3600


@dataclass(frozen=True, slots=True)
class PairingOutcome:
    status: ErpStatus
    check: ErpHealth | None
    check_error: str | None


class ErpPairingService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        store: SecretsStore,
        config: Settings,
        client: ErpPairingClient,
        connector: ErpConnectorService,
        *,
        rotation_grace_s: int = DEFAULT_ROTATION_GRACE_S,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._store = store
        self._config = config
        self._client = client
        self._connector = connector
        self._grace = timedelta(seconds=rotation_grace_s)

    # ── Подключить ERP ──────────────────────────────────────────────────────────────────────────

    async def pair(
        self, who: Principal, *, base_url: str, code: str, password: str
    ) -> PairingOutcome:
        url = normalize_base_url(base_url)
        if (problem := base_url_problem(url)) is not None:
            raise ValidationFailedError(
                f"erp base url is invalid: {problem}",
                reason=Reason.ERP_INVALID_URL,
                field="base_url",
            )
        code = "".join(code.split())  # код вводят руками: пробелы по краям и внутри не в счёт
        if not code:
            raise ValidationFailedError(
                "pairing code is empty", reason=Reason.ERP_PAIRING_CODE_INVALID, field="code"
            )
        self._require_secrets_key()
        await self._connector.confirm_password(who.user_id, password)
        before = await self._connector.audit_facts()

        generated = PairingSecrets.generate()
        await self._client.accept(url, code, generated)  # ошибка кода/сети — ничего не изменилось

        try:
            await self._save_paired(who, url, generated, before)
        except Exception:
            # ERP приняла ключи, а у нас не сохранились: нужен новый код (значения не логируются).
            logger.error("erp_pairing_local_save_failed", user_id=who.user_id, exc_info=True)
            raise
        logger.info("erp_paired", user_id=who.user_id)
        return await self._outcome()

    async def _save_paired(
        self, who: Principal, url: str, secrets_: PairingSecrets, before: dict[str, object]
    ) -> None:
        current = (await self._settings.get()).integrations
        payload = current.model_dump(mode="json")
        payload["erp_base_url"] = url
        payload["erp_previous_secret_until"] = None
        await self._settings.update(SETTINGS_KEY, payload, who.user_id)
        async with self._sessions() as session, session.begin():
            await self._store.put(
                session, ERP_SERVICE_TOKEN, secrets_.crm_to_erp_token, who.user_id
            )
            await self._store.put(
                session, ERP_INBOUND_TOKEN, secrets_.erp_to_crm_token, who.user_id
            )
            await self._store.put(session, ERP_WEBHOOK_SECRET, secrets_.webhook_secret, who.user_id)
            await self._store.delete(session, ERP_WEBHOOK_SECRET_PREVIOUS)
            after = {
                **before,
                "base_url": url,
                f"{ERP_SERVICE_TOKEN}_last4": last4(secrets_.crm_to_erp_token),
                f"{ERP_INBOUND_TOKEN}_last4": last4(secrets_.erp_to_crm_token),
                f"{ERP_WEBHOOK_SECRET}_last4": last4(secrets_.webhook_secret),
                f"{ERP_WEBHOOK_SECRET_PREVIOUS}_last4": None,
            }
            await audit.record(
                session,
                who.actor,
                "integrations.erp.pair",
                "integration",
                "erp",
                before=before,
                after=after,
            )

    # ── Обновить ключи ──────────────────────────────────────────────────────────────────────────

    async def rotate(self, who: Principal, *, password: str) -> PairingOutcome:
        resolution = await self._connector.resolution()
        connection = resolution.connection
        if connection is None:
            raise ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)
        self._require_secrets_key()
        await self._connector.confirm_password(who.user_id, password)
        before = await self._connector.audit_facts()

        old_webhook = resolution.webhook_secret
        stored_webhook = await self._store.get(ERP_WEBHOOK_SECRET)
        stored_previous = await self._store.get(ERP_WEBHOOK_SECRET_PREVIOUS)
        until = datetime.now(UTC) + self._grace
        generated = PairingSecrets.generate()

        # 1. CRM принимает оба секрета вебхуков ещё до того, как ERP начнёт подписывать новым.
        await self._put_webhook_secrets(
            who, current=generated.webhook_secret, previous=old_webhook or None, until=until
        )
        # 2. ERP принимает тройку под действующим токеном; прежний токен живёт переходный срок.
        try:
            rotated = await self._client.rotate(connection.base_url, connection.token, generated)
        except DomainError:
            await self._restore_webhook_secrets(who, stored_webhook, stored_previous)
            raise
        # 3. Теперь токены у нас: CRM→ERP — новый, ERP→CRM — новый.
        try:
            async with self._sessions() as session, session.begin():
                await self._store.put(
                    session, ERP_SERVICE_TOKEN, generated.crm_to_erp_token, who.user_id
                )
                await self._store.put(
                    session, ERP_INBOUND_TOKEN, generated.erp_to_crm_token, who.user_id
                )
                after = {
                    **before,
                    f"{ERP_SERVICE_TOKEN}_last4": last4(generated.crm_to_erp_token),
                    f"{ERP_INBOUND_TOKEN}_last4": last4(generated.erp_to_crm_token),
                    f"{ERP_WEBHOOK_SECRET}_last4": last4(generated.webhook_secret),
                    "previous_token_valid_until": rotated.previous_token_valid_until.isoformat(),
                }
                await audit.record(
                    session,
                    who.actor,
                    "integrations.erp.rotate",
                    "integration",
                    "erp",
                    before=before,
                    after=after,
                )
        except Exception:
            # Прежний токен в ERP ещё действует: админ успеет повторить (значения в лог не идут).
            logger.error("erp_rotation_local_save_failed", user_id=who.user_id, exc_info=True)
            raise
        logger.info("erp_keys_rotated", user_id=who.user_id)
        return await self._outcome()

    async def _put_webhook_secrets(
        self, who: Principal, *, current: str, previous: str | None, until: datetime | None
    ) -> None:
        async with self._sessions() as session, session.begin():
            await self._store.put(session, ERP_WEBHOOK_SECRET, current, who.user_id)
            if previous:
                await self._store.put(session, ERP_WEBHOOK_SECRET_PREVIOUS, previous, who.user_id)
            else:
                await self._store.delete(session, ERP_WEBHOOK_SECRET_PREVIOUS)
        integrations = (await self._settings.get()).integrations
        payload = integrations.model_dump(mode="json")
        payload["erp_previous_secret_until"] = until.isoformat() if previous and until else None
        await self._settings.update(SETTINGS_KEY, payload, who.user_id)

    async def _restore_webhook_secrets(
        self, who: Principal, stored_current: str | None, stored_previous: str | None
    ) -> None:
        """ERP ротацию не приняла: возвращаем секреты вебхуков как были (в БД или в `.env`, если
        строк не было)."""
        try:
            async with self._sessions() as session, session.begin():
                if stored_current:
                    await self._store.put(session, ERP_WEBHOOK_SECRET, stored_current, who.user_id)
                else:
                    await self._store.delete(session, ERP_WEBHOOK_SECRET)
                if stored_previous:
                    await self._store.put(
                        session, ERP_WEBHOOK_SECRET_PREVIOUS, stored_previous, who.user_id
                    )
                else:
                    await self._store.delete(session, ERP_WEBHOOK_SECRET_PREVIOUS)
            integrations = (await self._settings.get()).integrations
            payload = integrations.model_dump(mode="json")
            payload["erp_previous_secret_until"] = None
            await self._settings.update(SETTINGS_KEY, payload, who.user_id)
        except Exception:
            logger.error("erp_rotation_restore_failed", user_id=who.user_id, exc_info=True)

    # ── Общее ───────────────────────────────────────────────────────────────────────────────────

    def _require_secrets_key(self) -> None:
        if not self._store.enabled:
            raise ConflictError("SECRETS_KEY is not set", reason=Reason.SECRETS_KEY_MISSING)

    async def _outcome(self) -> PairingOutcome:
        """«Проверить связь» сразу после действия: сбой проверки не отменяет сопряжение, а
        объясняется."""
        self._connector.forget_cache()
        check: ErpHealth | None = None
        check_error: str | None = None
        try:
            check = await self._connector.check()
        except DomainError as exc:
            check_error = str(exc.details.get("reason") or exc.code)
        return PairingOutcome(await self._connector.status(), check, check_error)
