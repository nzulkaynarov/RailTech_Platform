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
from app.integrations.docling import DoclingClient
from app.integrations.litellm import Embedder, make_client
from app.integrations.litellm_catalog import ModelCatalog
from app.integrations.s3 import ObjectStorage
from app.security.secrets_store import SecretCipher, SecretsStore
from app.services.settings import SettingsService

if TYPE_CHECKING:
    from app.services.assist import AssistService
    from app.services.auth import AuthService
    from app.services.backups import BackupService
    from app.services.budget import BudgetGuard
    from app.services.client_contacts import ClientContactService
    from app.services.clients import ClientService
    from app.services.documents import DocumentService
    from app.services.kb.admin import KbAdminService
    from app.services.kb.ingest import KbIngestService
    from app.services.kb.search import KbSearchService
    from app.services.lead_messenger import LeadMessenger
    from app.services.leads import LeadService
    from app.services.llm_usage import DbUsageRecorder
    from app.services.setup import SetupService
    from app.services.users import UserService


@dataclass
class Container:
    settings: Settings

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
    def embedder(self) -> Embedder:
        return Embedder(self.llm, usage=self.usage_recorder)

    @cached_property
    def storage(self) -> ObjectStorage:
        return ObjectStorage(self.settings)

    @cached_property
    def settings_service(self) -> SettingsService:
        return SettingsService(self.session_factory)

    @cached_property
    def docling(self) -> DoclingClient:
        return DoclingClient(self.settings)

    @cached_property
    def auth_service(self) -> "AuthService":
        from app.services.auth import AuthService

        return AuthService(self.session_factory, self.settings)

    @cached_property
    def user_service(self) -> "UserService":
        from app.security.reauth import LockoutPolicy
        from app.services.users import UserService

        return UserService(
            self.session_factory,
            LockoutPolicy(self.settings.login_max_failures, self.settings.login_lockout_minutes),
        )

    @cached_property
    def setup_service(self) -> "SetupService":
        from app.repositories import users as users_repo
        from app.services.setup import SetupService

        async def count_admins() -> int:
            async with self.session_factory() as session:
                return await users_repo.count_active_admins(session)

        return SetupService(count_admins, self.user_service.create_first_admin)

    @cached_property
    def backup_service(self) -> "BackupService":
        from app.services.backups import BackupService

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
        )

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
    def kb_ingest(self) -> "KbIngestService":
        from app.services.kb.ingest import KbIngestService

        return KbIngestService(
            self.session_factory,
            self.storage,
            self.docling,
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

        return ClientService(self.session_factory, self.settings_service, self.lead_messenger)

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
    def secrets_store(self) -> SecretsStore:
        cipher = SecretCipher.optional(self.settings.secrets_key.get_secret_value())
        return SecretsStore(self.session_factory, cipher)

    @cached_property
    def _bots(self) -> dict[str, Bot]:
        return {}

    async def telegram_bot(self) -> Bot | None:
        """Клиент Bot API для исходящих сообщений с действующим токеном (БД или env); None — нет.

        Токен перечитывается при каждом вызове: смена в «Подключениях» действует и в воркере.
        """
        from app.integrations.telegram import resolve_token

        token, _ = await resolve_token(self.secrets_store, self.settings)
        if not token:
            return None
        bot = self._bots.get(token)
        if bot is None:
            bot = self._bots[token] = Bot(token)
        return bot

    async def aclose(self) -> None:
        for bot in self._bots.values():
            await bot.session.close()
        if "engine" in self.__dict__:
            await self.engine.dispose()


class CurrentBotSender:
    """`TextSender` для `LeadMessenger`: бот с действующим токеном на момент отправки."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def send_message(self, chat_id: int, text: str) -> Any:
        bot = await self._container.telegram_bot()
        if bot is None:
            raise RuntimeError("telegram bot token is not configured")
        return await bot.send_message(chat_id, text)


async def _enqueue_ingest(document_id: int) -> object:
    from app.tasks.ingest import enqueue_ingest

    return await enqueue_ingest(document_id, force=True)


async def _enqueue_extraction(document_id: int) -> object:
    from app.tasks.documents import extract_document_text

    return await extract_document_text.defer_async(document_id=document_id)


async def _escalation_changed(escalation_id: int) -> None:
    from app.tasks.notify import enqueue_escalation

    await enqueue_escalation(escalation_id, new=False)


async def _lead_assigned(lead_id: int, user_id: int) -> None:
    from app.tasks.notify import enqueue_handover

    await enqueue_handover(lead_id, user_id)


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
