"""Приложение BFF Платформы: маршруты /api/v1 (контракт — openapi/platform-bff.yaml)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app import __version__
from app.api import admin_roles, admin_users, auth, dashboard, health, me, notifications, search
from app.clients import CrmClient, ErpClient
from app.clients.base import TIMEOUT_SECONDS
from app.config import Settings, get_settings
from app.errors import install_error_handlers
from app.logging import configure_logging
from app.request_id import RequestIdMiddleware

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        redis = Redis.from_url(
            cfg.redis_url,
            socket_connect_timeout=TIMEOUT_SECONDS,
            socket_timeout=TIMEOUT_SECONDS,
        )
        crm = CrmClient(cfg.crm_url)
        erp = ErpClient(cfg.erp_url, cfg.erp_refresh_cookie)
        app.state.redis, app.state.crm, app.state.erp = redis, crm, erp
        app.state.settings = cfg
        try:
            yield
        finally:
            await crm.aclose()
            await erp.aclose()
            await redis.aclose()

    # Документация API — контракт в packages/contracts; /docs и схема FastAPI не публикуются.
    app = FastAPI(
        title="RailTech Platform BFF",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(me.router, prefix=API_PREFIX)
    app.include_router(admin_users.router, prefix=API_PREFIX)
    app.include_router(admin_roles.router, prefix=API_PREFIX)
    app.include_router(dashboard.router, prefix=API_PREFIX)
    app.include_router(notifications.router, prefix=API_PREFIX)
    app.include_router(search.router, prefix=API_PREFIX)
    return app


app = create_app()
