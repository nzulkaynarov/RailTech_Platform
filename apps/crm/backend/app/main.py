"""FastAPI app factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from rt_bus.fastapi import bus_router

from app import db
from app.api import errors, health
from app.api.cors import WebLeadCorsMiddleware
from app.api.v1 import (
    admin,
    ai_spend,
    auth,
    bus,
    client_contacts,
    clients,
    deals,
    export,
    external_services,
    integrations,
    kb,
    lead_intake,
    leads,
    me,
    models_admin,
    platform_roles,
    reply_templates,
    sandbox,
    setup,
    spend,
    stream,
    system,
    system_status,
    users,
)
from app.api.v1 import settings as settings_api
from app.bus import runtime as bus_runtime
from app.config import Settings, get_settings
from app.container import Container
from app.integrations import litellm, s3
from app.log import BusCorrelationMiddleware, configure_logging, is_valid_request_id
from app.schemas.errors import ErrorOut
from app.services.readiness import ReadinessService
from app.tasks.lifespan import queue_lifespan


async def _issue_setup_code(container: Container) -> None:
    """Первый запуск: код мастера в лог один раз; БД недоступна — код выдаст `/setup/state`."""
    try:
        await container.setup_service.ensure_code()
    except Exception as exc:  # noqa: BLE001 — старт api не должен падать из-за мастера
        structlog.get_logger(__name__).warning("setup_code_deferred", error=repr(exc))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = Container(settings)
        engine = container.engine
        async with (
            httpx.AsyncClient(timeout=settings.ready_check_timeout_s) as http,
            queue_lifespan(settings),
        ):
            # Бота в этом процессе нет: Telegram принимает `crm-bot` (`python -m app bot`, S0-4).
            app.state.container = container
            bus_runtime.install(container)
            await _issue_setup_code(container)
            app.state.engine = engine
            app.state.http = http
            app.state.readiness = ReadinessService(
                probes={
                    "database": lambda: db.ping(engine),
                    "s3": lambda: s3.ping(http, settings.s3_endpoint),
                    "litellm": lambda: litellm.ping(http, settings.litellm_base_url),
                },
                timeout_s=settings.ready_check_timeout_s,
            )
            yield
            broker = getattr(app.state, "broker", None)
            if broker is not None:
                await broker.stop()
            await container.drain_bus()  # пробуждения шины идут в очередь: она ещё открыта
        bus_runtime.install(None)
        await container.aclose()

    app = FastAPI(
        title="RailTech CRM API",
        version="0.5.0",  # 0.5.0 (W13C-F1): ключи erp, mail, first_employee в чек-листе
        lifespan=lifespan,
        # operationId = имя функции роута → читаемые имена в клиенте orval.
        generate_unique_id_function=lambda route: route.name,
        # Ошибки — единый формат `ErrorOut` (app/api/errors.py) вместо HTTPValidationError.
        responses={422: {"model": ErrorOut, "description": "Ошибка валидации"}},
    )
    # Порядок: добавленный раньше — глубже. Корреляция шины читает id, который ставит
    # `CorrelationIdMiddleware`, поэтому лежит под ним.
    app.add_middleware(BusCorrelationMiddleware)
    app.add_middleware(
        CorrelationIdMiddleware, header_name="X-Request-ID", validator=is_valid_request_id
    )
    if settings.cabinet_origins:
        # Только форма «Запрос» со страницы входа Cabinet; остальной API — same-origin (M3-CRM-05).
        app.add_middleware(WebLeadCorsMiddleware, origins=settings.cabinet_origins)
    app.include_router(health.router)
    # Приёмник шины rt_bus (CONTRACTS §9): только внутренняя сеть, Caddy `/bus/*` не публикует.
    app.include_router(bus_router(lambda: app.state.container.bus))
    errors.install(app)
    routers = (
        auth,
        me,
        users,
        platform_roles,
        # Раньше `leads`: `/leads/web*` не должен перехватываться `/leads/{lead_id}`.
        lead_intake,
        leads,
        stream,
        kb,
        settings_api,
        admin,
        clients,
        client_contacts,
        deals,
        setup,
        system,
        spend,
        ai_spend,
        external_services,
        models_admin,
        integrations,
        bus,
        system_status,
        sandbox,
        reply_templates,
        export,
    )
    for module in routers:
        router = module.router
        app.include_router(router)
    return app
