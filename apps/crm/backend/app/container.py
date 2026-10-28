"""Зависимости процесса (api, worker, MCP): движок БД, S3, шлюз моделей, docling.

Создаются лениво, один раз на процесс. Тесты подменяют отдельные части,
передавая их в сервисы напрямую.
"""

from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import TYPE_CHECKING, Any, Literal

from aiogram import Bot
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import db
from app.config import Settings, get_settings
from app.domain.errors import ConflictError, Reason
from app.domain.start_link import link_key
from app.integrations.docling import DoclingClient
from app.integrations.litellm import Embedder, make_client
from app.integrations.litellm_admin import LiteLLMAdmin
from app.integrations.litellm_catalog import ModelCatalog
from app.integrations.s3 import ObjectStorage
from app.security.secrets_store import SecretCipher, SecretsStore
from app.services.bot_state import BotStateService
from app.services.service_switches import SwitchBoard
from app.services.settings import SettingsService

if TYPE_CHECKING:
    from app.bus.notices import ErpEventNotices
    from app.bus.runtime import CrmBus
    from app.domain.backoffice import BackofficeMode
    from app.integrations.erp import ErpClient
    from app.integrations.erp_externals import ErpSwitchClient
    from app.integrations.erp_transport import SharedAsyncClient
    from app.services.ai_spend import AiSpendService
    from app.services.assist import AssistService
    from app.services.auth import AuthService
    from app.services.backups import BackupReader
    from app.services.budget import BudgetGuard
    from app.services.client_contacts import ClientContactService
    from app.services.client_notices import ClientNoticeService
    from app.services.client_requests import ClientRequestService
    from app.services.clients import ClientService
    from app.services.documents import DocumentService
    from app.services.erp_access import ErpAccessService
    from app.services.erp_client_card import ErpClientCardService
    from app.services.erp_connector import ErpConnectorService
    from app.services.erp_events import ErpEventsService
    from app.services.erp_handoff import ErpHandoffService
    from app.services.erp_pairing import ErpPairingService
    from app.services.erp_requests import ErpRequestService
    from app.services.external_services.checks import ExternalChecks
    from app.services.external_services.switches import SwitchService
    from app.services.external_services.view import ExternalServicesView
    from app.services.kb.admin import KbAdminService
    from app.services.kb.ingest import KbIngestService
    from app.services.kb.markdown_convert import MarkdownConverter
    from app.services.kb.search import KbSearchService
    from app.services.lead_consent import LeadConsentService
    from app.services.lead_intake import LeadIntakeService, WebLeadFollowUp
    from app.services.lead_messenger import LeadMessenger
    from app.services.leads import LeadService
    from app.services.llm_usage import DbUsageRecorder
    from app.services.mail import MailService
    from app.services.password_reset import PasswordResetService
    from app.services.platform_roles import PlatformRoleService
    from app.services.portal_invites import PortalInviteService
    from app.services.sandbox import SandboxService
    from app.services.setup import SetupService
    from app.services.smtp_connector import SmtpConnectorService
    from app.services.sso import SsoService
    from app.services.staff_deputy import StaffDeputyService
    from app.services.staff_link_notice import StaffLinkNotice
    from app.services.staff_notifications import StaffNotificationService
    from app.services.staff_notifier import StaffNotifier
    from app.services.staff_profile import StaffProfileService
    from app.services.staff_telegram_link import StaffTelegramLinkService
    from app.services.staff_tickets import StaffTicketService
    from app.services.user_invites import UserInviteService
    from app.services.users import UserService


@dataclass
class Container:
    settings: Settings

    def __post_init__(self) -> None:
        from app.integrations import langfuse

        # Выключатель «Langfuse» (ADR-0024): трейсы не пишутся, пока сервис выключен вручную.
        langfuse.set_gate(lambda: self.switch_board.peek("langfuse"))

    @cached_property
    def engine(self) -> AsyncEngine:
        return db.create_engine(self.settings)

    @cached_property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return db.create_session_factory(self.engine)

    @cached_property
    def llm(self) -> AsyncOpenAI:
        return make_client(self.settings)

    @cached_property
    def model_catalog(self) -> ModelCatalog:
        return ModelCatalog(self.settings.litellm_base_url, self.settings.litellm_api_key)

    @cached_property
    def litellm_admin(self) -> LiteLLMAdmin:
        return LiteLLMAdmin(self.settings.litellm_base_url, self.settings.litellm_api_key)

    @cached_property
    def switch_board(self) -> SwitchBoard:
        """Выключатели внешних сервисов (ADR-0024): кэш 10 с в каждом процессе."""
        return SwitchBoard(self.session_factory)

    @cached_property
    def external_switches(self) -> "SwitchService":
        from app.security.reauth import LockoutPolicy
        from app.services.external_services.switches import SwitchService

        return SwitchService(
            self.session_factory,
            self.litellm_admin,
            self.model_catalog,
            self.mail_service,
            self.switch_board,
            lockout=LockoutPolicy(
                self.settings.login_max_failures, self.settings.login_lockout_minutes
            ),
            erp_switch=self.erp_switch_client,
        )

    @cached_property
    def erp_http(self) -> "SharedAsyncClient":
        """Один HTTP-клиент на процесс для вызовов CRM → ERP (S0-6); закрывается в `aclose()`."""
        from app.integrations.erp_transport import SharedAsyncClient

        return SharedAsyncClient()

    @cached_property
    def erp_switch_client(self) -> "ErpSwitchClient":
        """Выключатели сервисов ERP (M3-ERP-06): `PUT /externals/{code}/switch`."""
        from app.integrations.erp_externals import HttpxErpSwitchClient

        return HttpxErpSwitchClient(
            self.secrets_store, self.settings, self.settings_service, http=self.erp_http
        )

    @cached_property
    def external_view(self) -> "ExternalServicesView":
        from app.services.external_services.view import ExternalServicesView

        return ExternalServicesView(
            self.session_factory,
            self.model_catalog,
            self.settings_service,
            self.switch_board,
            defaults=self.settings.litellm_models_path,
            stand=self.settings.is_stand,
        )

    @cached_property
    def external_checks(self) -> "ExternalChecks":
        """Центр внешних сервисов (M3-CRM-12): пробы, инциденты, оповещения."""
        from app.services.external_services.wiring import build_checks

        return build_checks(self)

    @cached_property
    def usage_recorder(self) -> "DbUsageRecorder":
        from app.services.llm_usage import DbUsageRecorder

        return DbUsageRecorder(
            self.session_factory, self.model_catalog, self.settings.llm_usage_kind
        )

    @cached_property
    def budget_guard(self) -> "BudgetGuard":
        from app.services.budget import BudgetGuard

        return BudgetGuard(self.session_factory, self.settings_service, self.model_catalog)

    @cached_property
    def ai_spend(self) -> "AiSpendService":
        """«Расходы» по ансамблю (M3-CRM-09): журнал LiteLLM `/spend/logs/v2`, кэш 60 с."""
        from app.integrations.litellm_spend import LiteLLMSpendLogs
        from app.services.ai_spend import AiSpendService

        source = LiteLLMSpendLogs(self.settings.litellm_base_url, self.settings.litellm_api_key)
        return AiSpendService(source, self.settings_service)

    @cached_property
    def embedder(self) -> Embedder:
        return Embedder(self.llm, usage=self.usage_recorder)

    @cached_property
    def storage(self) -> ObjectStorage:
        return ObjectStorage(self.settings)

    @cached_property
    def settings_service(self) -> SettingsService:
        return SettingsService(
            self.session_factory,
            crm_base_url_default=self.settings.crm_base_url_default,
            platform_url=self.settings.platform_base_url,
        )

    @cached_property
    def docling(self) -> DoclingClient:
        return DoclingClient(self.settings)

    @cached_property
    def kb_converter(self) -> "MarkdownConverter":
        from app.services.kb.markdown_convert import MarkdownConverter

        return MarkdownConverter()

    @cached_property
    def auth_service(self) -> "AuthService":
        from app.services.auth import AuthService

        return AuthService(self.session_factory, self.settings)

    @cached_property
    def sso_service(self) -> "SsoService":
        from app.services.sso import SsoService

        return SsoService(self.session_factory, self.settings, self.auth_service)

    @cached_property
    def user_service(self) -> "UserService":
        from app.security.reauth import LockoutPolicy
        from app.services.users import UserService

        return UserService(
            self.session_factory,
            LockoutPolicy(self.settings.login_max_failures, self.settings.login_lockout_minutes),
            erp_sync=_enqueue_erp_sync,
        )

    @cached_property
    def platform_role_service(self) -> "PlatformRoleService":
        """Роли Платформы как данные (R-1): изменение роли пересчитывает права её сотрудников."""
        from app.services.platform_roles import PlatformRoleService

        return PlatformRoleService(self.session_factory, erp_sync=_enqueue_erp_sync)

    @cached_property
    def erp_access_service(self) -> "ErpAccessService":
        """Доступ сотрудников к ERP (FIX-11): провижининг и отзыв сессий в задачах очереди."""
        from app.integrations.erp_users import HttpxErpUsersClient
        from app.services.erp_access import ErpAccessService

        client = HttpxErpUsersClient(
            self.secrets_store, self.settings, self.settings_service, http=self.erp_http
        )
        return ErpAccessService(self.session_factory, client)

    @cached_property
    def setup_service(self) -> "SetupService":
        from app.repositories import users as users_repo
        from app.services.setup import SetupService

        async def count_admins() -> int:
            async with self.session_factory() as session:
                return await users_repo.count_active_admins(session)

        return SetupService(count_admins, self.user_service.create_first_admin)

    @cached_property
    def backup_service(self) -> "BackupReader":
        """Статус бэкапов: том (dev) или бакет `backups` RustFS (прод, M5-CRM-01) — по настройке."""
        from app.services.backups import BackupService
        from app.services.backups_rustfs import RustfsBackupService

        if self.settings.backup_source_resolved == "rustfs":
            return RustfsBackupService(self.storage, self.settings.s3_bucket_backups)
        return BackupService(self.settings.backup_dir)

    @cached_property
    def lead_messenger(self) -> "LeadMessenger":
        from app.services.lead_messenger import DryRunSender, LeadMessenger

        if self.settings.telegram_dry_run:
            return LeadMessenger(self.session_factory, DryRunSender())
        return LeadMessenger(self.session_factory, CurrentBotSender(self))

    @cached_property
    def lead_service(self) -> "LeadService":
        from app.services.leads import LeadService

        return LeadService(
            self.session_factory,
            self.settings_service,
            self.lead_messenger,
            on_escalation_changed=_escalation_changed,
            on_assigned=_lead_assigned,
            on_escalation_reopened=_escalation_reopened,
            on_chats_changed=_chats_changed,
            backoffice_mode=self.backoffice_mode,
        )

    @cached_property
    def lead_consent_service(self) -> "LeadConsentService":
        """«Согласие получено» сотрудником за лида, заведённого вручную (FIX-57, D-8)."""
        from app.services.lead_consent import LeadConsentService

        return LeadConsentService(self.session_factory)

    @cached_property
    def lead_intake(self) -> "LeadIntakeService":
        """Форма «Запрос» с сайта и «Новый лид» вручную (M3-CRM-05); окно по IP — в процессе api."""
        from app.services.lead_intake import LeadIntakeService

        return LeadIntakeService(
            self.session_factory,
            self.settings_service,
            self.settings.jwt_secret.get_secret_value().encode("utf-8"),
            notices=self.client_notice_service,
            on_web_lead=_enqueue_web_lead,
        )

    @cached_property
    def client_notice_service(self) -> "ClientNoticeService":
        """Подтверждение запроса с сайта клиенту и итог отправки (D1-9, `client_notices`)."""
        from app.services.client_notices import ClientNoticeService

        return ClientNoticeService(
            self.session_factory,
            self.settings_service,
            self.mail_service,
            self.telegram_bot,
            self._bot_username,
            link_key(self.settings.jwt_secret.get_secret_value().encode("utf-8")),
            self.settings,
        )

    async def _bot_username(self) -> str | None:
        snapshot = await self.bot_state.snapshot()
        return snapshot.username if snapshot is not None else None

    @cached_property
    def assist_service(self) -> "AssistService":
        from app.agents.llm import ChatModel
        from app.services.assist import AssistService, DbAssistStore, KbFragments
        from app.services.budget import BudgetedModel

        usage = self.usage_recorder

        def model(purpose: Literal["assist_draft", "assist_improve"]) -> BudgetedModel:
            return BudgetedModel(
                ChatModel(self.llm, "dialog-model", usage=usage, purpose=purpose),
                ChatModel(self.llm, "fallback-model", usage=usage, purpose=purpose),
                self.budget_guard,
            )

        return AssistService(
            self.settings_service,
            DbAssistStore(self.session_factory),
            KbFragments(self.kb_search),
            {"draft": model("assist_draft"), "improve": model("assist_improve")},
            self.budget_guard,
        )

    @cached_property
    def sandbox_service(self) -> "SandboxService":
        """«Проверить бота»: диалог из CRM через тот же контур, что и Telegram-бот."""
        from app.bot.setup import SandboxConversation
        from app.services.sandbox import SandboxService

        return SandboxService(
            self.session_factory, self.settings_service, SandboxConversation(self)
        )

    @cached_property
    def kb_ingest(self) -> "KbIngestService":
        from app.services.kb.ingest import KbIngestService

        return KbIngestService(
            self.session_factory,
            self.storage,
            self.kb_converter,
            self.embedder,
            self.settings.s3_bucket_kb,
        )

    @cached_property
    def kb_search(self) -> "KbSearchService":
        from app.services.kb.search import KbSearchService

        return KbSearchService(self.session_factory, self.embedder)

    @cached_property
    def kb_admin(self) -> "KbAdminService":
        from app.services.kb.admin import KbAdminService

        return KbAdminService(self.session_factory, self.kb_ingest, _enqueue_ingest)

    @cached_property
    def client_service(self) -> "ClientService":
        from app.services.clients import ClientService

        return ClientService(
            self.session_factory,
            self.settings_service,
            self.lead_messenger,
            on_chats_changed=_chats_changed,
            backoffice_mode=self.backoffice_mode,
            erp_handoff_enqueue=_enqueue_erp_handoff,
        )

    @cached_property
    def erp_handoff_service(self) -> "ErpHandoffService":
        """Передача клиента в ERP задачей после коммита (FIX-31)."""
        from app.services.erp_handoff import ErpHandoffService

        return ErpHandoffService(self.session_factory, self.erp_client)

    @cached_property
    def client_request_service(self) -> "ClientRequestService":
        """«Создать заявку» из лида и клиента (CRM-03, W16-D1-2)."""
        from app.services.client_requests import ClientRequestService

        return ClientRequestService(
            self.session_factory,
            backoffice_mode=self.backoffice_mode,
            enqueue=_enqueue_erp_request,
            on_chats_changed=_chats_changed,
        )

    @cached_property
    def erp_request_service(self) -> "ErpRequestService":
        """Заявка CRM → ERP задачей после коммита (шов 0.9.0)."""
        from app.integrations.erp_requests import HttpxErpRequestClient
        from app.services.erp_requests import ErpRequestService

        client = HttpxErpRequestClient(
            self.secrets_store, self.settings, self.settings_service, http=self.erp_http
        )
        return ErpRequestService(self.session_factory, client, self.erp_handoff_service)

    @cached_property
    def erp_client(self) -> "ErpClient":
        """Клиент интеграции ERP (M3-CRM-03): передача клиента (handoff)."""
        from app.integrations.erp import HttpxErpClient

        return HttpxErpClient(
            self.secrets_store, self.settings, self.settings_service, http=self.erp_http
        )

    @cached_property
    def erp_client_card(self) -> "ErpClientCardService":
        """Данные ERP в карточке клиента CRM (шов 0.3.0): долг по валютам."""
        from app.integrations.erp_company import HttpxErpCompanyClient
        from app.services.erp_client_card import ErpClientCardService

        company = HttpxErpCompanyClient(
            self.secrets_store, self.settings, self.settings_service, http=self.erp_http
        )
        return ErpClientCardService(self.session_factory, company)

    @cached_property
    def erp_connector(self) -> "ErpConnectorService":
        """Коннектор «ERP» (M3-CRM-02): адрес и секреты из «Подключений», проба `/health`, кэш."""
        from app.integrations.erp import HttpxErpProbe
        from app.security.reauth import LockoutPolicy
        from app.services.erp_connector import ErpConnectorService

        return ErpConnectorService(
            self.session_factory,
            self.settings_service,
            self.secrets_store,
            self.settings,
            HttpxErpProbe(http=self.erp_http),
            lockout=LockoutPolicy(
                self.settings.login_max_failures, self.settings.login_lockout_minutes
            ),
        )

    @cached_property
    def erp_pairing(self) -> "ErpPairingService":
        """Сопряжение с ERP по одноразовому коду и ротация ключей (M3-CRM-10)."""
        from app.integrations.erp_pairing import HttpxErpPairingClient
        from app.services.erp_pairing import ErpPairingService

        return ErpPairingService(
            self.session_factory,
            self.settings_service,
            self.secrets_store,
            self.settings,
            HttpxErpPairingClient(http=self.erp_http),
            self.erp_connector,
        )

    @cached_property
    def erp_notices(self) -> "ErpEventNotices":
        """Сообщения Telegram по событиям ERP: после коммита обработки (`app.bus.notices`)."""
        from app.bus.notices import ErpEventNotices

        return ErpEventNotices(
            self.session_factory, self.telegram_bot, self.settings, mail=self.mail_service
        )

    @cached_property
    def erp_events_service(self) -> "ErpEventsService":
        """Обработчики событий ERP, принятых с шины (M3-CRM-04, B4)."""
        from app.services.erp_acceptance_code import AcceptanceCodeDelivery
        from app.services.erp_events import ErpEventsService
        from app.services.erp_invite_delivery import InviteDelivery

        return ErpEventsService(
            self.settings_service,
            self.erp_notices,
            AcceptanceCodeDelivery(
                self.session_factory, self.settings_service, self.telegram_bot, self.settings
            ),
            InviteDelivery(
                self.session_factory,
                self.settings_service,
                self.telegram_bot,
                self.settings,
                self.portal_invites,
            ),
        )

    @cached_property
    def portal_invites(self) -> "PortalInviteService":
        """Итог приглашения в кабинет и повторная отправка другим каналом (D1-9)."""
        from app.services.portal_invites import PortalInviteService

        return PortalInviteService(self.session_factory, self.erp_client)

    @cached_property
    def bus(self) -> "CrmBus":
        """Шина процесса (rt_bus, сервис `crm`): публикация, доставка, приёмник, обработка inbox."""
        from app.bus import handlers  # noqa: F401 — регистрирует обработчики событий ERP
        from app.bus.runtime import build_bus
        from app.tasks.bus import tasks

        return build_bus(
            lambda: self.session_factory(),
            self._bus_webhook_secrets,
            after_processed=self.erp_notices.deliver,
            enqueue=tasks.enqueue,
            wakeup=tasks.wakeup,
        )

    async def _bus_webhook_secrets(self) -> tuple[str, ...]:
        """Секреты вебхуков сопряжения CRM ↔ ERP: из них выводятся секреты пар шины (L12)."""
        from app.integrations.erp import resolve_erp

        resolution = await resolve_erp(self.secrets_store, self.settings, self.settings_service)
        return resolution.webhook_secrets

    @cached_property
    def mail_service(self) -> "MailService":
        """Коннектор «Почта» (M3-CRM-08): рендер, журнал `email_log`, отправка задачей очереди."""
        from app.integrations.smtp import SmtplibTransport
        from app.services.mail import MailService

        return MailService(
            self.session_factory,
            self.secrets_store,
            SecretCipher.optional(self.settings.secrets_key.get_secret_value()),
            self.settings,
            self.settings_service,
            SmtplibTransport(),
            _enqueue_email,
            paused=self._mail_paused,
        )

    async def _mail_paused(self) -> bool:
        return await self.switch_board.is_disabled("mail")

    @cached_property
    def smtp_connector(self) -> "SmtpConnectorService":
        from app.security.reauth import LockoutPolicy
        from app.services.smtp_connector import SmtpConnectorService

        return SmtpConnectorService(
            self.session_factory,
            self.settings_service,
            self.secrets_store,
            self.mail_service,
            lockout=LockoutPolicy(
                self.settings.login_max_failures, self.settings.login_lockout_minutes
            ),
        )

    @cached_property
    def user_invites(self) -> "UserInviteService":
        from app.services.user_invites import UserInviteService

        return UserInviteService(
            self.session_factory,
            self.mail_service,
            self.settings_service,
            self.settings.platform_base_url,
        )

    @cached_property
    def staff_profile(self) -> "StaffProfileService":
        """Профиль сотрудника: поля, имя и фото в бакете файлов CRM (W15-H6)."""
        from app.services.staff_profile import StaffProfileService

        return StaffProfileService(
            self.session_factory,
            self.user_service,
            self.storage,
            self.settings.s3_bucket_documents,
        )

    @cached_property
    def staff_telegram_link(self) -> "StaffTelegramLinkService":
        from app.services.staff_telegram_link import StaffTelegramLinkService

        return StaffTelegramLinkService(
            self.session_factory, self.bot_state, on_linked=self.staff_link_notice.linked
        )

    @cached_property
    def staff_link_notice(self) -> "StaffLinkNotice":
        from app.services.staff_link_notice import StaffLinkNotice

        return StaffLinkNotice(
            self.session_factory,
            self.mail_service,
            self.settings_service,
            self.settings.platform_base_url,
            self.staff_notifications,
        )

    @cached_property
    def staff_deputy(self) -> "StaffDeputyService":
        from app.services.staff_deputy import StaffDeputyService

        return StaffDeputyService(self.session_factory)

    @cached_property
    def staff_notifications(self) -> "StaffNotificationService":
        """Колокольчик сотрудника: события CRM (ответ на обращение, привязка Telegram, W15-H7)."""
        from app.services.staff_notifications import StaffNotificationService

        return StaffNotificationService(self.session_factory)

    @cached_property
    def staff_tickets(self) -> "StaffTicketService":
        """Обращения сотрудников к администратору (W15-H7); личные сообщения — через бота CRM."""
        from app.services.staff_tickets import StaffTicketService

        return StaffTicketService(
            self.session_factory, self._staff_messenger, self.settings.platform_base_url
        )

    async def _staff_messenger(self) -> "StaffNotifier | None":
        from app.services.staff_notifier import StaffNotifier

        bot = await self.telegram_bot()
        return StaffNotifier(self.session_factory, bot) if bot is not None else None

    @cached_property
    def password_reset(self) -> "PasswordResetService":
        """«Забыли пароль?»: ссылка на Платформу (`PLATFORM_PUBLIC_URL`) по почте или в Telegram."""
        from app.services.password_reset import PasswordResetService

        return PasswordResetService(
            self.session_factory,
            self.mail_service,
            self.settings_service,
            self.telegram_bot,
            self.settings.platform_base_url,
        )

    async def backoffice_mode(self) -> "BackofficeMode":
        """Режим жизненного цикла (ADR-0022): `erp`, когда коннектор настроен, иначе `local`."""
        return await self.erp_connector.mode()

    @cached_property
    def contact_service(self) -> "ClientContactService":
        from app.services.client_contacts import ClientContactService

        return ClientContactService(self.session_factory)

    @cached_property
    def document_service(self) -> "DocumentService":
        from app.services.documents import DocumentService

        return DocumentService(
            self.session_factory,
            self.storage,
            self.docling,
            self.settings.s3_bucket_documents,
            _enqueue_extraction,
        )

    @cached_property
    def bot_state(self) -> BotStateService:
        """Состояние `crm-bot` в БД: статус для «Подключений» и перезапуск при смене токена."""
        return BotStateService(self.session_factory, stale_after_s=self.settings.bot_stale_after_s)

    @cached_property
    def secrets_store(self) -> SecretsStore:
        cipher = SecretCipher.optional(self.settings.secrets_key.get_secret_value())
        return SecretsStore(self.session_factory, cipher)

    @cached_property
    def _bots(self) -> dict[str, Bot]:
        return {}

    async def telegram_bot(self) -> Bot | None:
        """Клиент Bot API для исходящих сообщений с действующим токеном (БД или env); None — нет.

        Токен перечитывается при каждом вызове: смена в «Подключениях» действует и в воркере.
        Telegram выключен вручную (центр внешних сервисов, ADR-0024) — None: исходящие на паузе.
        """
        from app.integrations.telegram import make_bot, resolve_token

        if await self.switch_board.is_disabled("telegram"):
            return None

        token, _ = await resolve_token(self.secrets_store, self.settings)
        if not token:
            return None
        bot = self._bots.get(token)
        if bot is None:
            bot = self._bots[token] = make_bot(self.settings, token)
        return bot

    async def drain_bus(self) -> None:
        """Дождаться пробуждений шины (B5a): вызывать, пока очередь Procrastinate ещё открыта."""
        if "bus" in self.__dict__:
            await self.bus.drain_wakeups()

    async def aclose(self) -> None:
        if "sandbox_service" in self.__dict__:
            await self.sandbox_service.aclose()
        for bot in self._bots.values():
            await bot.session.close()
        if "bus" in self.__dict__:
            await self.bus.aclose()
        if "erp_http" in self.__dict__:
            await self.erp_http.aclose()
        if "engine" in self.__dict__:
            await self.engine.dispose()


class CurrentBotSender:
    """`TextSender` для `LeadMessenger`: бот с действующим токеном на момент отправки."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def send_message(self, chat_id: int, text: str) -> Any:
        if await self._container.switch_board.is_disabled("telegram"):
            raise ConflictError("telegram is paused", reason=Reason.TELEGRAM_PAUSED)
        bot = await self._container.telegram_bot()
        if bot is None:
            raise RuntimeError("telegram bot token is not configured")
        return await bot.send_message(chat_id, text)


async def _enqueue_ingest(document_id: int) -> object:
    from procrastinate.exceptions import AlreadyEnqueued

    from app.tasks.ingest import enqueue_ingest

    try:
        return await enqueue_ingest(document_id, force=True)
    except AlreadyEnqueued as exc:
        # Замок `kb-document-N`: ингест этого документа уже стоит в очереди — повторять не нужно
        # (C2A-G-6: раньше это было 500 «CRM не отвечает»).
        raise ConflictError("document is already queued", reason=Reason.DOCUMENT_INDEXING) from exc


async def _enqueue_web_lead(follow_up: "WebLeadFollowUp") -> None:
    from app.tasks.client_notices import enqueue_web_lead

    await enqueue_web_lead(follow_up)


async def _enqueue_email(email_log_id: int) -> object:
    from app.tasks.mail import enqueue_email

    return await enqueue_email(email_log_id)


async def _enqueue_extraction(document_id: int) -> object:
    from app.tasks.documents import extract_document_text

    return await extract_document_text.defer_async(document_id=document_id)


async def _enqueue_erp_sync(action: str, user_id: int) -> int | None:
    from app.tasks.erp_users import enqueue_erp_sync

    return await enqueue_erp_sync(action, user_id)


async def _enqueue_erp_request(deal_id: int, client_id: int, user_id: int) -> object:
    from app.tasks.erp_requests import enqueue_erp_request

    return await enqueue_erp_request(deal_id, client_id, user_id)


async def _enqueue_erp_handoff(client_id: int, lead_id: int, user_id: int) -> object:
    from app.tasks.erp_handoff import enqueue_erp_handoff

    return await enqueue_erp_handoff(client_id, lead_id, user_id)


async def _escalation_changed(escalation_id: int) -> None:
    from app.tasks.notify import enqueue_escalation

    await enqueue_escalation(escalation_id, new=False)


async def _escalation_reopened(escalation_id: int) -> None:
    """Передача снова открыта («Вернуть из отложенных»): пост и проверка SLA в новый срок."""
    from app.tasks.notify import enqueue_escalation

    await enqueue_escalation(escalation_id, new=True)


async def _chats_changed(tg_user_ids: list[int]) -> None:
    """Статус лида в CRM изменился — меню его чата в Telegram сразу, без ожидания сообщения."""
    from app.tasks.notify import enqueue_chat_menus

    await enqueue_chat_menus(tg_user_ids)


async def _lead_assigned(lead_id: int, user_id: int) -> None:
    from app.tasks.notify import enqueue_handover

    await enqueue_handover(lead_id, user_id)


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
