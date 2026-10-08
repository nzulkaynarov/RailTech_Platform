"""FastAPI app factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI

from app import db
from app.api import health
from app.config import Settings, get_settings
from app.integrations import litellm, s3
from app.log import configure_logging
from app.services.readiness import ReadinessService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = db.create_engine(settings)
        async with httpx.AsyncClient(timeout=settings.ready_check_timeout_s) as http:
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
        await engine.dispose()

    app = FastAPI(
        title="RailTech CRM API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(CorrelationIdMiddleware, header_name="X-Request-ID")
    app.include_router(health.router)
    return app
