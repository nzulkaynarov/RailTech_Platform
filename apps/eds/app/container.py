"""Зависимости процесса (api, worker): движок БД, шина. Создаются лениво, один раз на процесс."""

from dataclasses import dataclass
from functools import cached_property, lru_cache

from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import db
from app.bus.runtime import build_bus
from app.config import Settings, get_settings
from app.services.render_process import ProcessRenderer
from app.services.storage import ObjectStorage, build_storage


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
    def storage(self) -> ObjectStorage:
        return build_storage(self.settings)

    @cached_property
    def bus(self) -> AsyncBus:
        if self.settings.app_env == "test":  # очереди в тестах нет: обработку inbox и пробуждение вызывает сам тест
            return build_bus(self.session_factory)
        from app.tasks.bus import tasks  # лениво: модуль задач сам берёт контейнер

        return build_bus(self.session_factory, enqueue=tasks.enqueue, wakeup=tasks.wakeup)

    @cached_property
    def renderer(self) -> ProcessRenderer:
        """Рендер PDF письма в отдельном процессе (B-094); тесты подменяют `render`."""
        return ProcessRenderer()

    @cached_property
    def deferred_renders(self) -> list[str]:
        """Тесты: хеши, поставленные в очередь (очереди нет — задачу вызывает сам тест через `renders.run`)."""
        return []

    async def defer_render(self, render_hashes: list[str]) -> None:
        """Поставить рендеры в очередь после коммита (задача одна на хеш — `queueing_lock`)."""
        if not render_hashes:
            return
        if self.settings.app_env == "test":
            self.deferred_renders.extend(render_hashes)
            return
        from app.tasks.renders import defer  # лениво: модуль задач сам берёт контейнер

        await defer(render_hashes)

    async def drain_bus(self) -> None:
        """Дождаться пробуждений шины (B5a): вызывать, пока очередь Procrastinate ещё открыта."""
        if "bus" in self.__dict__:
            await self.bus.drain_wakeups()

    async def aclose(self) -> None:
        if "bus" in self.__dict__:
            await self.bus.aclose()
        if "renderer" in self.__dict__:
            self.renderer.close()
        if "engine" in self.__dict__:
            await self.engine.dispose()


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
