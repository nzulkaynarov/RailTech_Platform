from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app

CONTRACT = Path(__file__).resolve().parents[4] / "packages/contracts/openapi/platform-bff.yaml"

CRM_URL = "http://crm.test"
ERP_URL = "http://erp.test"


@pytest.fixture(scope="session")
def contract() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def settings() -> Settings:
    # Redis по умолчанию недоступен (порт 1): тесты, которым нужен рабочий Redis, подменяют ресурс.
    return Settings(
        PLATFORM_CRM_URL=CRM_URL,
        PLATFORM_ERP_URL=ERP_URL,
        REDIS_URL="redis://127.0.0.1:1/0",
        LOG_LEVEL="WARNING",
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://bff.test") as http:
        yield http
