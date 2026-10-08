"""Зависимости процесса (api, worker, MCP): движок БД, S3, шлюз моделей, docling.

Создаются лениво, один раз на процесс. Тесты подменяют отдельные части,
передавая их в сервисы напрямую.
"""

from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import TYPE_CHECKING

from aiogram import Bot
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import db
from app.config import Settings, get_settings
from app.integrations.docling import DoclingClient
from app.integrations.litellm import Embedder, make_client
from app.integrations.s3 import ObjectStorage
from app.services.settings import SettingsService

if TYPE_CHECKING:
    from app.services.auth import AuthService
    from app.services.kb.admin import KbAdminService
    from app.services.kb.ingest import KbIngestService
    from app.services.kb.search import KbSearchService
    from app.services.lead_messenger import LeadMessenger
    from app.services.leads import LeadService
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
    def embedder(self) -> Embedder:
        return Embedder(self.llm)

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
        from app.services.users import UserService

        return UserService(self.session_factory)

    @cached_property
    def lead_messenger(self) -> "LeadMessenger":
        from app.services.lead_messenger import DryRunSender, LeadMessenger

        if self.settings.telegram_dry_run:
            return LeadMessenger(self.session_factory, DryRunSender())
        return LeadMessenger(self.session_factory, self.telegram_bot)

    @cached_property
    def lead_service(self) -> "LeadService":
        from app.services.leads import LeadService

        return LeadService(
            self.session_factory,
            self.settings_service,
            self.lead_messenger,
            on_escalation_changed=_escalation_changed,
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
    def telegram_bot(self) -> Bot | None:
        """Клиент Bot API для исходящих сообщений (воркер); None без токена."""
        token = self.settings.telegram_bot_token.get_secret_value()
        return Bot(token) if token else None

    async def aclose(self) -> None:
        if "telegram_bot" in self.__dict__ and self.telegram_bot is not None:
            await self.telegram_bot.session.close()
        if "engine" in self.__dict__:
            await self.engine.dispose()


async def _enqueue_ingest(document_id: int) -> object:
    from app.tasks.ingest import enqueue_ingest

    return await enqueue_ingest(document_id, force=True)


async def _escalation_changed(escalation_id: int) -> None:
    from app.tasks.notify import enqueue_escalation

    await enqueue_escalation(escalation_id, new=False)


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
