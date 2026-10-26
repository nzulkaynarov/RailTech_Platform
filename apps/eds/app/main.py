"""FastAPI app factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from rt_bus.fastapi import CorrelationMiddleware, bus_router

from app import errors
from app.api import health
from app.api.v1 import ROUTERS
from app.config import Settings, get_settings
from app.container import Container
from app.log import AccessLogMiddleware, configure_logging


@asynccontextmanager
async def _queue_lifespan(settings: Settings) -> AsyncIterator[None]:
    """Очередь нужна API, чтобы ставить обработку принятых событий; в тестах (`APP_ENV=test`) не открывается."""
    if settings.app_env == "test":
        yield
        return
    from app.tasks.queue import queue

    async with queue.open_async():
        yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = Container(settings)
        app.state.container = container
        async with _queue_lifespan(settings):
            yield
            await container.drain_bus()  # пробуждения шины идут в очередь: она ещё открыта
        await container.aclose()

    app = FastAPI(
        title="RailTech EDS API",
        version="0.2.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        # Контракт — packages/contracts/openapi/eds.yaml; описание из кода только вне прода (сверка в разработке).
        openapi_url=None if settings.app_env == "prod" else "/openapi.json",
        generate_unique_id_function=lambda route: route.name,
    )
    # Добавленный раньше — глубже: корреляция (X-Request-ID) ставится снаружи журнала запросов.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.include_router(health.router)
    # Приёмник шины rt_bus: только внутренняя сеть, у EDS нет внешнего маршрута в Caddy (ADR-0015).
    app.include_router(bus_router(lambda: app.state.container.bus))
    errors.install(app)
    for router in ROUTERS:
        app.include_router(router)
    return app
