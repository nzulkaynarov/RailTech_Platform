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
from typing import Any, Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.erp_connector import base_url_problem, normalize_base_url, requires_https
from app.domain.errors import (
    ConflictError,
    DomainError,
    Reason,
    ValidationFailedError,
)
from app.integrations.erp import ErpHealth
from app.integrations.erp_pairing import AmbiguousOutcomeError, ErpPairingClient, PairingSecrets
from app.security import audit
from app.security.principal import Principal
from app.security.secrets_store import (
    ERP_INBOUND_TOKEN,
    ERP_PENDING_INBOUND_TOKEN,
    ERP_PENDING_SERVICE_TOKEN,
    ERP_PENDING_WEBHOOK_SECRET,
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
        self, who: Principal, *, base_url: str, code: str | None, password: str
    ) -> PairingOutcome:
        """«Подключить ERP» — только по кнопке админа (без автопопыток при старте и проверке связи).

        С кодом из ERP — по коду; без кода — первое сопряжение по общему секрету платформы
        (bootstrap, ADR-0009): ERP принимает его один раз за жизнь, дальше — только код.
        """
        url = normalize_base_url(base_url)
        if (problem := base_url_problem(url)) is not None:
            raise ValidationFailedError(
                f"erp base url is invalid: {problem}",
                reason=Reason.ERP_INVALID_URL,
                field="base_url",
            )
        if self._config.app_env == "prod" and requires_https(url):
            raise ValidationFailedError(
                "erp base url must be https in production",
                reason=Reason.ERP_HTTPS_REQUIRED,
                field="base_url",
            )
        code = "".join((code or "").split())  # код вводят руками: пробелы вокруг и внутри не в счёт
        platform_secret = next(iter(self._config.platform_sso_secrets), "")
        if not code and not platform_secret:
            raise ValidationFailedError(
                "no pairing code and no shared platform secret",
                reason=Reason.ERP_BOOTSTRAP_UNAVAILABLE,
                field="code",
            )
        self._require_secrets_key()
        await self._connector.confirm_password(who.user_id, password)
        before = await self._connector.audit_facts()

        generated = PairingSecrets.generate()
        # Ошибка кода, доказательства или сети — ничего не изменилось.
        if code:
            await self._client.accept(url, code, generated)
        else:
            await self._client.accept_bootstrap(url, platform_secret, generated)
        method = "code" if code else "bootstrap"

        try:
            await self._save_paired(who, url, generated, before, method)
        except Exception:
            # ERP приняла ключи, а у нас не сохранились: нужен новый код (значения не логируются).
            logger.error("erp_pairing_local_save_failed", user_id=who.user_id, exc_info=True)
            raise
        logger.info("erp_paired", user_id=who.user_id, method=method)
        return await self._outcome()

    async def _save_paired(
        self,
        who: Principal,
        url: str,
        secrets_: PairingSecrets,
        before: dict[str, object],
        method: str,
    ) -> None:
        """Адрес, ключи и аудит — одной транзакцией: либо всё, либо ничего."""
        payload = await self._settings_payload(erp_base_url=url, erp_previous_secret_until=None)
        async with self._sessions() as session, session.begin():
            await self._settings.update_in(session, SETTINGS_KEY, payload, who.user_id)
            await self._store.put(
                session, ERP_SERVICE_TOKEN, secrets_.crm_to_erp_token, who.user_id
            )
            await self._store.put(
                session, ERP_INBOUND_TOKEN, secrets_.erp_to_crm_token, who.user_id
            )
            await self._store.put(session, ERP_WEBHOOK_SECRET, secrets_.webhook_secret, who.user_id)
            await self._store.delete(session, ERP_WEBHOOK_SECRET_PREVIOUS)
            await self._delete_pending(session)  # новое сопряжение заменяет и неоконченную ротацию
            after = {
                **before,
                "base_url": url,
                "method": method,  # кто нажал — в `actor`; способ: по коду из ERP или bootstrap
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
        self._settings.invalidate()

    # ── Обновить ключи ──────────────────────────────────────────────────────────────────────────

    async def rotate(self, who: Principal, *, password: str) -> PairingOutcome:
        """«Обновить ключи» с «ожидающей» тройкой.

        Тройка сохраняется до ответа ERP и фиксируется только после явного успеха. Исход после
        отправки мог быть любым (ReadTimeout, 5xx, обрыв) — тогда ничего не откатывается: ERP могла
        уже перейти на новые значения, и откат сломал бы вебхуки. Повтор шлёт ТУ ЖЕ тройку (ERP
        идемпотентна по ней). Откат — только при однозначном отказе (ConnectError, 4xx) первой же
        попытки.
        """
        resolution = await self._connector.resolution()
        connection = resolution.connection
        if connection is None:
            raise ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)
        self._require_secrets_key()
        await self._connector.confirm_password(who.user_id, password)
        before = await self._connector.audit_facts()

        until = datetime.now(UTC) + self._grace
        generated = await self._load_pending()
        fresh = generated is None
        if generated is None:
            generated = PairingSecrets.generate()
            stored_webhook = await self._store.get(ERP_WEBHOOK_SECRET)
            stored_previous = await self._store.get(ERP_WEBHOOK_SECRET_PREVIOUS)
            await self._begin_rotation(who, generated, resolution.webhook_secret or None, until)
        else:
            # Повтор: CRM уже принимает оба секрета; срок приёма предыдущего продлеваем.
            await self._extend_transition(who, until)
        try:
            rotated = await self._client.rotate(connection.base_url, connection.token, generated)
        except AmbiguousOutcomeError:
            logger.warning("erp_rotation_outcome_unknown", user_id=who.user_id)
            raise  # ничего не откатываем; повтор отправит ту же тройку
        except DomainError:
            if fresh:
                await self._abort_rotation(who, stored_webhook, stored_previous)
            raise
        try:
            await self._commit_rotation(who, generated, before, rotated.previous_token_valid_until)
        except Exception:
            # Прежний токен в ERP ещё действует, тройка сохранена как ожидающая: повтор безопасен.
            logger.error("erp_rotation_local_save_failed", user_id=who.user_id, exc_info=True)
            raise
        logger.info("erp_keys_rotated", user_id=who.user_id)
        return await self._outcome()

    async def _begin_rotation(
        self, who: Principal, triple: PairingSecrets, old_webhook: str | None, until: datetime
    ) -> None:
        """Ожидающая тройка + оба секрета вебхуков + срок приёма предыдущего — одной транзакцией."""
        payload = await self._settings_payload(
            erp_previous_secret_until=until.isoformat() if old_webhook else None
        )
        async with self._sessions() as session, session.begin():
            await self._store.put(
                session, ERP_PENDING_SERVICE_TOKEN, triple.crm_to_erp_token, who.user_id
            )
            await self._store.put(
                session, ERP_PENDING_INBOUND_TOKEN, triple.erp_to_crm_token, who.user_id
            )
            await self._store.put(
                session, ERP_PENDING_WEBHOOK_SECRET, triple.webhook_secret, who.user_id
            )
            await self._store.put(session, ERP_WEBHOOK_SECRET, triple.webhook_secret, who.user_id)
            if old_webhook:
                await self._store.put(
                    session, ERP_WEBHOOK_SECRET_PREVIOUS, old_webhook, who.user_id
                )
            else:
                await self._store.delete(session, ERP_WEBHOOK_SECRET_PREVIOUS)
            await self._settings.update_in(session, SETTINGS_KEY, payload, who.user_id)
        self._settings.invalidate()

    async def _extend_transition(self, who: Principal, until: datetime) -> None:
        payload = await self._settings_payload(erp_previous_secret_until=until.isoformat())
        async with self._sessions() as session, session.begin():
            await self._settings.update_in(session, SETTINGS_KEY, payload, who.user_id)
        self._settings.invalidate()

    async def _commit_rotation(
        self,
        who: Principal,
        triple: PairingSecrets,
        before: dict[str, object],
        previous_token_valid_until: datetime,
    ) -> None:
        async with self._sessions() as session, session.begin():
            await self._store.put(session, ERP_SERVICE_TOKEN, triple.crm_to_erp_token, who.user_id)
            await self._store.put(session, ERP_INBOUND_TOKEN, triple.erp_to_crm_token, who.user_id)
            await self._delete_pending(session)
            after = {
                **before,
                f"{ERP_SERVICE_TOKEN}_last4": last4(triple.crm_to_erp_token),
                f"{ERP_INBOUND_TOKEN}_last4": last4(triple.erp_to_crm_token),
                f"{ERP_WEBHOOK_SECRET}_last4": last4(triple.webhook_secret),
                "previous_token_valid_until": previous_token_valid_until.isoformat(),
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

    async def _abort_rotation(
        self, who: Principal, stored_current: str | None, stored_previous: str | None
    ) -> None:
        """ERP однозначно отказала: тройка удаляется, секреты вебхуков — как были (БД, `.env`)."""
        try:
            payload = await self._settings_payload(erp_previous_secret_until=None)
            async with self._sessions() as session, session.begin():
                await self._delete_pending(session)
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
                await self._settings.update_in(session, SETTINGS_KEY, payload, who.user_id)
            self._settings.invalidate()
        except Exception:
            logger.error("erp_rotation_restore_failed", user_id=who.user_id, exc_info=True)

    async def _load_pending(self) -> PairingSecrets | None:
        service = await self._store.get(ERP_PENDING_SERVICE_TOKEN)
        inbound = await self._store.get(ERP_PENDING_INBOUND_TOKEN)
        webhook = await self._store.get(ERP_PENDING_WEBHOOK_SECRET)
        if service and inbound and webhook:
            return PairingSecrets(service, inbound, webhook)
        return None

    async def _delete_pending(self, session: AsyncSession) -> None:
        for key in (
            ERP_PENDING_SERVICE_TOKEN,
            ERP_PENDING_INBOUND_TOKEN,
            ERP_PENDING_WEBHOOK_SECRET,
        ):
            await self._store.delete(session, key)

    async def _settings_payload(self, **changes: object) -> dict[str, Any]:
        payload = (await self._settings.get()).integrations.model_dump(mode="json")
        payload.update(changes)
        return payload

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
