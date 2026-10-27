from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import jsonschema
import pytest
import respx
import yaml
from fastapi import FastAPI

from app.config import Settings
from app.cookies import CSRF_COOKIE, CSRF_HEADER
from app.main import create_app
from tests.backends import PASSWORD, Backends
from tests.consts import CRM_URL, EDS_URL, ERP_URL
from tests.fakes import Clock, FakeRedis
from tests.roles import Role

CONTRACT = Path(__file__).resolve().parents[4] / "packages/contracts/openapi/platform-bff.yaml"


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
        PLATFORM_EDS_URL=EDS_URL,
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


# --- вход, сессия, RBAC (PLT-10, PLT-11) ----------------------------------------------------------


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr("app.session.now", c)
    monkeypatch.setattr("app.auth.now", c)
    return c


@pytest.fixture
def be(clock: Clock) -> Iterator[Backends]:
    with respx.mock(assert_all_called=False) as router:
        yield Backends(router, clock)


class ContractChecker:
    """Проверка ответов BFF по схемам packages/contracts/openapi/platform-bff.yaml."""

    def __init__(self, contract: dict[str, Any]) -> None:
        self.contract = contract

    def _resolve(self, node: dict[str, Any]) -> dict[str, Any]:
        ref = node.get("$ref")
        if ref is None:
            return node
        target: Any = self.contract
        for part in ref.removeprefix("#/").split("/"):
            target = target[part]
        resolved: dict[str, Any] = target
        return resolved

    def __call__(self, response: httpx.Response, path: str, method: str) -> httpx.Response:
        operation = self.contract["paths"][path][method]
        declared = operation["responses"].get(str(response.status_code))
        assert declared is not None, f"{method} {path}: статус {response.status_code} не описан"
        spec = self._resolve(declared)
        content = spec.get("content", {}).get("application/json")
        if content is None:
            assert not response.content, f"{method} {path}: тело там, где его нет в контракте"
            return response
        schema = {**content["schema"], "components": self.contract["components"]}
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
            response.json()
        )
        return response


@pytest.fixture
def check(contract: dict[str, Any]) -> ContractChecker:
    return ContractChecker(contract)


@dataclass
class Web:
    """BFF поверх ASGI: браузерный клиент (cookie-jar), Redis в памяти, CRM и ERP на respx."""

    client: httpx.AsyncClient
    redis: FakeRedis
    be: Backends
    app: FastAPI
    clock: Clock

    @property
    def csrf(self) -> str:
        return self.client.cookies.get(CSRF_COOKIE) or ""

    @property
    def sid(self) -> str:
        return self.client.cookies.get("rt_pf_session") or ""

    async def login(
        self,
        roles: list[Role] | None = None,
        *,
        password: str = PASSWORD,
        email: str = "ivan.test@example.org",
        ip: str | None = None,
    ) -> httpx.Response:
        if roles is not None:
            self.be.set_roles(roles)
        headers = {"X-Forwarded-For": ip} if ip else {}
        return await self.client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}, headers=headers
        )

    async def send(
        self,
        method: Literal["POST", "PATCH", "PUT", "DELETE"],
        url: str,
        *,
        json: Any = None,
        csrf: str | None = None,
    ) -> httpx.Response:
        headers = {CSRF_HEADER: self.csrf if csrf is None else csrf}
        return await self.client.request(method, url, json=json, headers=headers)


@pytest.fixture
async def web(app: FastAPI, clock: Clock, be: Backends) -> AsyncIterator[Web]:
    redis = FakeRedis(clock)
    app.state.redis = redis
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://bff.test") as http:
        yield Web(client=http, redis=redis, be=be, app=app, clock=clock)
