"""Зависимости процесса (api, worker, MCP): движок БД, S3, шлюз моделей, docling.

Создаются лениво, один раз на процесс. Тесты подменяют отдельные части,
передавая их в сервисы напрямую.
"""

from dataclasses import dataclass
from functools import cached_property, lru_cache

from aiogram import Bot
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import db
from app.config import Settings, get_settings
from app.integrations.docling import DoclingClient
from app.integrations.litellm import Embedder, make_client
from app.integrations.s3 import ObjectStorage
from app.services.settings import SettingsService


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
    def telegram_bot(self) -> Bot | None:
        """Клиент Bot API для исходящих сообщений (воркер); None без токена."""
        token = self.settings.telegram_bot_token.get_secret_value()
        return Bot(token) if token else None

    async def aclose(self) -> None:
        if "telegram_bot" in self.__dict__ and self.telegram_bot is not None:
            await self.telegram_bot.session.close()
        if "engine" in self.__dict__:
            await self.engine.dispose()


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
