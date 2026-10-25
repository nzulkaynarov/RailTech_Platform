"""Зависимости процесса (api, worker): движок БД, шина. Создаются лениво, один раз на процесс."""

from dataclasses import dataclass
from functools import cached_property, lru_cache

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import db
from app.bus.runtime import build_bus
from app.config import Settings, get_settings


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
    def bus(self) -> AsyncBus:
        if self.settings.app_env == "test":  # очереди в тестах нет: обработку inbox вызывает сам тест
            return build_bus(self.session_factory)
        from app.tasks.bus import tasks  # лениво: модуль задач сам берёт контейнер

        return build_bus(self.session_factory, enqueue=tasks.enqueue)

    async def aclose(self) -> None:
        if "bus" in self.__dict__:
            await self.bus.aclose()
        if "engine" in self.__dict__:
            await self.engine.dispose()


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
