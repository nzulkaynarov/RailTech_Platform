"""FastAPI app factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI

from app import db
from app.api import errors, health, telegram
from app.api.v1 import auth, leads, me, stream, users
from app.bot.setup import bot_lifespan
from app.config import Settings, get_settings
from app.container import Container
from app.integrations import litellm, s3
from app.log import configure_logging
from app.services.readiness import ReadinessService
from app.tasks.lifespan import queue_lifespan


async def _qualify(lead_id: int) -> None:
    from app.tasks.qualify import enqueue_qualify

    await enqueue_qualify(lead_id)


async def _escalated(lead_id: int, escalation_id: int) -> None:
    from app.tasks.notify import enqueue_escalation

    await enqueue_escalation(escalation_id)


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
            bot_lifespan(container, on_activity=_qualify, on_escalation=_escalated) as bot,
        ):
            app.state.container = container
            app.state.bot = bot
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
        await container.aclose()

    app = FastAPI(
        title="RailTech CRM API",
        version="0.1.0",
        lifespan=lifespan,
        # operationId = имя функции роута → читаемые имена в клиенте orval.
        generate_unique_id_function=lambda route: route.name,
    )
    app.add_middleware(CorrelationIdMiddleware, header_name="X-Request-ID")
    app.include_router(health.router)
    app.include_router(telegram.router)
    errors.install(app)
    for router in (auth.router, me.router, users.router, leads.router, stream.router):
        app.include_router(router)
    return app
