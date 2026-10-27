"""Приложение BFF Платформы: маршруты /api/v1 (контракт — openapi/platform-bff.yaml)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from rt_bus.fastapi import bus_router

from app import __version__
from app.api import (
    admin_audit,
    admin_bot,
    admin_bus,
    admin_company,
    admin_integrations,
    admin_passwords,
    admin_roles,
    admin_users,
    auth,
    bridge,
    crm_kb,
    dashboard,
    eds_documents,
    eds_letters,
    events,
    health,
    me,
    me_notifications,
    me_profile,
    notifications,
    search,
    setup,
)
from app.bus import create_receiver
from app.client_ip import ClientIpMiddleware
from app.clients import CrmClient, EdsClient, ErpClient
from app.clients.base import TIMEOUT_SECONDS
from app.config import Settings, get_settings
from app.errors import install_error_handlers
from app.hub import EventHub
from app.logging import configure_logging
from app.request_id import RequestIdMiddleware

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)

    # Подсказки шины → SSE (B5): Redis берётся при каждом обращении (`app.state.redis`).
    hub = EventHub(lambda: app.state.redis)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        redis = Redis.from_url(
            cfg.redis_url,
            socket_connect_timeout=TIMEOUT_SECONDS,
            socket_timeout=TIMEOUT_SECONDS,
        )
        crm = CrmClient(cfg.crm_url, cfg.crm_timeout_seconds)
        erp = ErpClient(cfg.erp_url, cfg.erp_refresh_cookie)
        eds = EdsClient(cfg.eds_url)
        app.state.redis, app.state.crm, app.state.erp = redis, crm, erp
        app.state.eds = eds
        app.state.settings = cfg
        app.state.hub = hub
        try:
            yield
        finally:
            await hub.aclose()
            await crm.aclose()
            await erp.aclose()
            await eds.aclose()
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
    app.add_middleware(ClientIpMiddleware, networks=cfg.trusted_proxy_networks)
    install_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(me.router, prefix=API_PREFIX)
    app.include_router(bridge.router, prefix=API_PREFIX)
    app.include_router(me_notifications.router, prefix=API_PREFIX)
    app.include_router(me_profile.router, prefix=API_PREFIX)
    app.include_router(admin_users.router, prefix=API_PREFIX)
    app.include_router(admin_passwords.router, prefix=API_PREFIX)
    app.include_router(setup.router, prefix=API_PREFIX)
    app.include_router(admin_roles.router, prefix=API_PREFIX)
    app.include_router(admin_audit.router, prefix=API_PREFIX)
    app.include_router(admin_integrations.router, prefix=API_PREFIX)
    app.include_router(admin_company.router, prefix=API_PREFIX)
    app.include_router(admin_bus.router, prefix=API_PREFIX)
    app.include_router(admin_bot.router, prefix=API_PREFIX)
    app.include_router(crm_kb.router, prefix=API_PREFIX)
    app.include_router(eds_documents.router, prefix=API_PREFIX)
    app.include_router(eds_letters.router, prefix=API_PREFIX)
    app.include_router(dashboard.router, prefix=API_PREFIX)
    app.include_router(notifications.router, prefix=API_PREFIX)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)
    # Приёмник шины rt_bus: POST /bus/v1/events (подпись пары издатель → platform-bff).
    app.include_router(bus_router(create_receiver(hub)))
    return app


app = create_app()
