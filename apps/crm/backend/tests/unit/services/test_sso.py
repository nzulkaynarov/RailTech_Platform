"""Unit-тесты для сервиса и эндпоинтов платформенного SSO (CRM ↔ ERP, CONTRACTS §6, M3-CRM-06).

Тестирует:
1. Выпуск SSO-токена в ERP (iss=crm, aud=erp, sub=crm_user_id, exp=iat+60, jti)
2. Обмен токена из ERP (iss=erp, aud=crm) на сессию CRM
3. Защиту от replay-атак (одноразовый jti)
4. Поддержку ротации секретов (подпись вторым активным ключом)
5. Отказ при деактивированном пользователе (403), невалидной подписи/iss/aud/exp (401)
6. REST API эндпоинты: POST /api/v1/auth/sso/token и POST /api/v1/auth/sso/exchange
"""

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import errors
from app.api.deps import get_container, get_principal
from app.api.v1.auth import router as auth_router
from app.config import Settings
from app.domain.errors import AuthError, ConflictError, ForbiddenError
from app.models.auth import SsoReplayToken, User
from app.security.principal import Principal
from app.services.auth import ClientInfo, Session
from app.services.sso import SsoService

SECRET_1 = "test-platform-sso-secret-primary-1234567890"
SECRET_2 = "test-platform-sso-secret-secondary-0987654321"


@pytest.fixture
def sso_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        postgres_host="db.invalid",
        postgres_password="test-password",
        platform_sso_secret=SecretStr(f"{SECRET_1},{SECRET_2}"),
        erp_frontend_url="http://erp.localhost",
        jwt_secret=SecretStr("crm-jwt-secret-at-least-32-chars-long"),
    )


def make_erp_sso_token(
    secret: str = SECRET_1,
    iss: str = "erp",
    aud: str = "crm",
    sub: str = "42",
    email: str = "manager@railtech.uz",
    name: str = "Менеджер Продаж",
    role: str = "manager",
    permissions: list[str] | None = None,
    ttl_s: int = 60,
    jti: str | None = None,
    now: int | None = None,
) -> str:
    iat = now if now is not None else int(time.time())
    payload = {
        "iss": iss,
        "aud": aud,
        "sub": str(sub),
        "email": email,
        "name": name,
        "role": role,
        "permissions": permissions or [],
        "iat": iat,
        "exp": iat + ttl_s,
        "jti": jti or str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


class FakeScalarsResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return self._items


class FakeAsyncSession:
    def __init__(
        self,
        users: dict[int, User],
        replay_jtis: set[str] | None = None,
        user_roles: dict[int, list[str]] | None = None,
    ) -> None:
        self.users = users
        self.replay_jtis = replay_jtis if replay_jtis is not None else set()
        self.user_roles = user_roles if user_roles is not None else {}
        self.added: list[Any] = []
        self.flushed = False

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def get(self, model: Any, ident: Any) -> Any:
        if model is User:
            return self.users.get(ident)
        if model is SsoReplayToken:
            return SsoReplayToken(jti=ident) if ident in self.replay_jtis else None
        return None

    async def scalar(self, stmt: Any) -> Any:
        # Поиск по email
        for user in self.users.values():
            return user
        return None

    async def scalars(self, stmt: Any) -> FakeScalarsResult:
        # Роли пользователя
        roles = []
        for _u_id, r_list in self.user_roles.items():
            roles.extend(r_list)
        if not roles and self.users:
            roles = ["admin"]
        return FakeScalarsResult(roles)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, SsoReplayToken):
            self.replay_jtis.add(obj.jti)

    async def flush(self) -> None:
        self.flushed = True

    async def execute(self, stmt: Any) -> None:
        pass


def make_session_factory(
    users: dict[int, User],
    replay_jtis: set[str] | None = None,
    user_roles: dict[int, list[str]] | None = None,
) -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeAsyncSession]:
        yield FakeAsyncSession(users, replay_jtis, user_roles)

    return factory


# ─── 1. Issue Token ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_sso_token_admin(sso_settings: Settings) -> None:
    admin_user = User(
        id=1,
        email="admin@railtech.uz",
        full_name="Администратор",
        is_active=True,
        must_change_password=False,
    )
    users = {1: admin_user}

    fake_auth = MagicMock()
    sso_svc = SsoService(make_session_factory(users), sso_settings, fake_auth)

    token, redirect_url = await sso_svc.issue_token(1)

    assert redirect_url == "http://erp.localhost/sso/exchange"
    assert token

    payload = jwt.decode(
        token,
        SECRET_1,
        algorithms=["HS256"],
        audience="erp",
        issuer="crm",
    )
    assert payload["iss"] == "crm"
    assert payload["aud"] == "erp"
    assert payload["sub"] == "1"
    assert payload["email"] == "admin@railtech.uz"
    assert payload["name"] == "Администратор"
    assert payload["exp"] == payload["iat"] + 60
    assert "jti" in payload


@pytest.mark.asyncio
async def test_issue_sso_token_inactive_user_raises_forbidden(sso_settings: Settings) -> None:
    inactive_user = User(
        id=2,
        email="inactive@railtech.uz",
        full_name="Неактивный",
        is_active=False,
        must_change_password=False,
    )
    users = {2: inactive_user}

    fake_auth = MagicMock()
    sso_svc = SsoService(make_session_factory(users), sso_settings, fake_auth)

    with pytest.raises(ForbiddenError):
        await sso_svc.issue_token(2)


def _active_user(user_id: int) -> User:
    return User(
        id=user_id,
        email=f"user{user_id}@railtech.uz",
        full_name="Сотрудник",
        is_active=True,
        must_change_password=False,
    )


@pytest.mark.asyncio
async def test_issue_sso_token_without_secret_is_refused(sso_settings: Settings) -> None:
    """FIX-01: запасного ключа в коде больше нет — без секрета SSO выключен."""
    settings = sso_settings.model_copy(update={"platform_sso_secret": SecretStr("")})
    sso_svc = SsoService(make_session_factory({1: _active_user(1)}), settings, MagicMock())

    with pytest.raises(ConflictError) as exc_info:
        await sso_svc.issue_token(1)
    assert exc_info.value.details["reason"] == "sso_not_configured"


@pytest.mark.asyncio
async def test_exchange_without_secret_rejects_any_token(sso_settings: Settings) -> None:
    settings = sso_settings.model_copy(update={"platform_sso_secret": SecretStr("")})
    sso_svc = SsoService(make_session_factory({42: _active_user(42)}), settings, MagicMock())
    token = make_erp_sso_token(secret="any-key-an-attacker-could-guess-0123456789")

    with pytest.raises(AuthError):
        await sso_svc.exchange_token(token, MagicMock())


# ─── 2. Exchange Token ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exchange_sso_token_success(sso_settings: Settings) -> None:
    user = User(
        id=42,
        email="manager@railtech.uz",
        full_name="Менеджер",
        is_active=True,
        must_change_password=False,
    )
    users = {42: user}
    replay_set: set[str] = set()

    fake_auth = MagicMock()
    mock_session = Session(
        access_token="mock_access",
        refresh_token="mock_refresh",
        user_id=42,
        roles=["manager"],
        must_change_password=False,
    )
    fake_auth._issue = AsyncMock(return_value=mock_session)

    sso_svc = SsoService(make_session_factory(users, replay_set), sso_settings, fake_auth)

    unique_jti = str(uuid.uuid4())
    token = make_erp_sso_token(sub="42", jti=unique_jti, name="Менеджер Обновлённый")

    session = await sso_svc.exchange_token(token, ClientInfo(ip="127.0.0.1"))

    assert session.access_token == "mock_access"
    assert session.user_id == 42
    assert user.full_name == "Менеджер Обновлённый"
    assert unique_jti in replay_set


@pytest.mark.asyncio
async def test_exchange_sso_token_secondary_secret_rotation(sso_settings: Settings) -> None:
    user = User(
        id=42,
        email="manager@railtech.uz",
        full_name="Менеджер",
        is_active=True,
        must_change_password=False,
    )
    users = {42: user}
    fake_auth = MagicMock()
    fake_auth._issue = AsyncMock(return_value=Session("acc", "ref", 42, ["manager"], False))

    sso_svc = SsoService(make_session_factory(users), sso_settings, fake_auth)

    # Подписан вторым секретом
    token = make_erp_sso_token(secret=SECRET_2, sub="42")
    session = await sso_svc.exchange_token(token, ClientInfo(ip="127.0.0.1"))
    assert session.access_token == "acc"


@pytest.mark.asyncio
async def test_exchange_sso_token_replay_rejected(sso_settings: Settings) -> None:
    user = User(
        id=42,
        email="manager@railtech.uz",
        full_name="Менеджер",
        is_active=True,
        must_change_password=False,
    )
    users = {42: user}
    used_jti = str(uuid.uuid4())
    replay_set = {used_jti}  # jti уже использован

    fake_auth = MagicMock()
    sso_svc = SsoService(make_session_factory(users, replay_set), sso_settings, fake_auth)

    token = make_erp_sso_token(sub="42", jti=used_jti)
    with pytest.raises(AuthError) as exc_info:
        await sso_svc.exchange_token(token, ClientInfo())
    assert "token already used" in str(exc_info.value)


@pytest.mark.asyncio
async def test_exchange_sso_token_expired_rejected(sso_settings: Settings) -> None:
    user = User(id=42, email="u@r.uz", full_name="U", is_active=True, must_change_password=False)
    sso_svc = SsoService(make_session_factory({42: user}), sso_settings, MagicMock())

    past = int(time.time()) - 100
    token = make_erp_sso_token(sub="42", now=past, ttl_s=60)
    with pytest.raises(AuthError):
        await sso_svc.exchange_token(token, ClientInfo())


@pytest.mark.asyncio
async def test_exchange_sso_token_wrong_aud_or_iss_rejected(sso_settings: Settings) -> None:
    user = User(id=42, email="u@r.uz", full_name="U", is_active=True, must_change_password=False)
    sso_svc = SsoService(make_session_factory({42: user}), sso_settings, MagicMock())

    token_wrong_aud = make_erp_sso_token(aud="other")
    with pytest.raises(AuthError):
        await sso_svc.exchange_token(token_wrong_aud, ClientInfo())

    token_wrong_iss = make_erp_sso_token(iss="other")
    with pytest.raises(AuthError):
        await sso_svc.exchange_token(token_wrong_iss, ClientInfo())


@pytest.mark.asyncio
async def test_exchange_sso_token_deactivated_user_raises_forbidden(sso_settings: Settings) -> None:
    user = User(id=42, email="u@r.uz", full_name="U", is_active=False, must_change_password=False)
    sso_svc = SsoService(make_session_factory({42: user}), sso_settings, MagicMock())

    token = make_erp_sso_token(sub="42")
    with pytest.raises(ForbiddenError):
        await sso_svc.exchange_token(token, ClientInfo())


# ─── 3. REST API Endpoints ────────────────────────────────────────────────────


@pytest.fixture
def api_client(sso_settings: Settings) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(auth_router)

    fake_sso_service = MagicMock()
    fake_sso_service.issue_token = AsyncMock(
        return_value=("fake_jwt_token", "http://erp.localhost/sso/exchange")
    )
    fake_sso_service.exchange_token = AsyncMock(
        return_value=Session(
            access_token="fake_access_123",
            refresh_token="fake_refresh_456",
            user_id=10,
            roles=["manager"],
            must_change_password=False,
        )
    )

    mock_container = SimpleNamespace(
        settings=sso_settings,
        sso_service=fake_sso_service,
    )
    app.dependency_overrides[get_container] = lambda: mock_container
    app.dependency_overrides[get_principal] = lambda: Principal(
        user_id=10,
        full_name="Тестовый Юзер",
        roles=("manager",),
        must_change_password=False,
        ip="127.0.0.1",
    )

    return TestClient(app)


def test_api_sso_token_endpoint(api_client: TestClient) -> None:
    resp = api_client.post("/api/v1/auth/sso/token")
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == "fake_jwt_token"
    assert data["redirect_url"] == "http://erp.localhost/sso/exchange"


def test_api_sso_exchange_endpoint(api_client: TestClient) -> None:
    resp = api_client.post("/api/v1/auth/sso/exchange", json={"token": "some_valid_jwt"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == "fake_access_123"
    assert data["token_type"] == "bearer"
    assert "rt_refresh" in resp.cookies
