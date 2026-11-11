"""Unit-тесты выдачи SSO-токена сотрудника для ERP (CONTRACTS §6, M3-CRM-06).

Тестирует:
1. Выпуск SSO-токена в ERP (iss=crm, aud=erp, sub=crm_user_id, exp=iat+60, jti)
2. Отказ без секрета, при выключенном SSO и у неактивного сотрудника
3. Токен — только при `"erp"` в `platform_access`; права в нём — коды каталога ERP (FIX-11)
4. REST API: POST /api/v1/auth/sso/token
"""

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
from sqlalchemy.dialects import postgresql

from app.api import errors
from app.api.deps import get_container, get_principal
from app.api.v1.auth import router as auth_router
from app.config import Settings
from app.domain.errors import ConflictError, ForbiddenError
from app.models.auth import SsoReplayToken, User
from app.security.principal import Principal
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
        platform_sso_enabled=True,
        jwt_secret=SecretStr("crm-jwt-secret-at-least-32-chars-long"),
    )


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
        # FIX-10: поиска пользователя по e-mail при обмене SSO больше нет.
        raise AssertionError("SsoService must not look users up by e-mail")

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

    async def execute(self, stmt: Any) -> "FakeResult":
        """`DELETE` устаревших jti — ничего; `INSERT … ON CONFLICT DO NOTHING` — занять jti."""
        if getattr(stmt, "is_insert", False):
            jti = stmt.compile(dialect=postgresql.dialect()).params["jti"]  # type: ignore[no-untyped-call]
            if jti in self.replay_jtis:
                return FakeResult(None)  # конфликт: строка не вставлена, RETURNING пуст
            self.replay_jtis.add(jti)
            self.added.append(SsoReplayToken(jti=jti))
            self.flushed = True
            return FakeResult(jti)
        return FakeResult(None)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


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
        platform_access=["crm", "erp"],
    )
    users = {1: admin_user}

    fake_auth = MagicMock()
    sso_svc = SsoService(make_session_factory(users), sso_settings, fake_auth)

    token = await sso_svc.issue_token(1)

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
        platform_access=["crm", "erp"],
    )
    users = {2: inactive_user}

    fake_auth = MagicMock()
    sso_svc = SsoService(make_session_factory(users), sso_settings, fake_auth)

    with pytest.raises(ForbiddenError):
        await sso_svc.issue_token(2)


def _active_user(user_id: int, platform_access: list[str] | None = None) -> User:
    return User(
        id=user_id,
        email=f"user{user_id}@railtech.uz",
        full_name="Сотрудник",
        is_active=True,
        must_change_password=False,
        platform_access=platform_access or ["crm", "erp"],
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
async def test_sso_is_refused_while_disabled(sso_settings: Settings) -> None:
    """FIX-03: до волны 1 переход выключен флагом PLATFORM_SSO_ENABLED (по умолчанию false)."""
    settings = sso_settings.model_copy(update={"platform_sso_enabled": False})
    user = _active_user(1)
    sso_svc = SsoService(make_session_factory({1: user}), settings, MagicMock())

    with pytest.raises(ForbiddenError):
        await sso_svc.issue_token(1)


def test_sso_is_disabled_by_default() -> None:
    assert Settings(_env_file=None).platform_sso_enabled is False


@pytest.fixture
def api_client(sso_settings: Settings) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(auth_router)

    fake_sso_service = MagicMock()
    fake_sso_service.issue_token = AsyncMock(return_value="fake_jwt_token")

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
    assert data == {"token": "fake_jwt_token"}


# ─── 4. platform_access и карта прав (FIX-11, S-5, S-11) ─────────────────────────────────────


def _decode_issued(token: str) -> dict[str, Any]:
    return jwt.decode(token, SECRET_1, algorithms=["HS256"], audience="erp", issuer="crm")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform_access", "allowed"),
    [
        pytest.param(["crm"], False, id="default-crm-only"),
        pytest.param(["crm", "erp"], True, id="erp-granted"),
        pytest.param([], False, id="empty"),
        pytest.param(None, False, id="never-set"),
    ],
)
async def test_issue_token_only_with_erp_in_platform_access(
    sso_settings: Settings, platform_access: list[str] | None, allowed: bool
) -> None:
    """Матрица «без доступа переключателя нет»: токен — только при `erp` в `platform_access`."""
    user = _active_user(1)
    user.platform_access = platform_access  # type: ignore[assignment]
    sso_svc = SsoService(make_session_factory({1: user}), sso_settings, MagicMock())

    if allowed:
        token = await sso_svc.issue_token(1)
        assert token
        return
    with pytest.raises(ForbiddenError) as exc_info:
        await sso_svc.issue_token(1)
    assert exc_info.value.details["reason"] == "platform_access_denied"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("roles", "role_claim", "forbidden"),
    [
        (["admin"], "admin", set()),
        (["manager"], "manager", {"quote.view_cost_margin", "finance.payment", "team.manage"}),
        (["viewer"], "viewer", {"quote.view_cost_margin", "deal.manage"}),
    ],
)
async def test_issued_token_permissions_are_erp_catalog_codes(
    sso_settings: Settings, roles: list[str], role_claim: str, forbidden: set[str]
) -> None:
    from app.domain.erp_permissions import ERP_PERMISSIONS

    sso_svc = SsoService(
        make_session_factory({1: _active_user(1)}, user_roles={1: roles}), sso_settings, MagicMock()
    )
    token = await sso_svc.issue_token(1)
    payload = _decode_issued(token)

    assert payload["role"] == role_claim
    assert set(payload["permissions"]) <= set(ERP_PERMISSIONS)
    assert not set(payload["permissions"]) & forbidden


@pytest.mark.asyncio
async def test_manager_token_has_no_cost_margin_permission(sso_settings: Settings) -> None:
    """S-11: раньше `quote.view_cost_margin` получал каждый менеджер."""
    sso_svc = SsoService(
        make_session_factory({1: _active_user(1)}, user_roles={1: ["manager"]}),
        sso_settings,
        MagicMock(),
    )
    token = await sso_svc.issue_token(1)
    assert "quote.view_cost_margin" not in _decode_issued(token)["permissions"]


def _matrix_client(settings: Settings, user: User) -> TestClient:
    """Настоящий `SsoService` за настоящим роутером: проверяем ответ API целиком."""
    app = FastAPI()
    errors.install(app)
    app.include_router(auth_router)
    sso = SsoService(make_session_factory({user.id: user}), settings, MagicMock())
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(
        settings=settings, sso_service=sso
    )
    app.dependency_overrides[get_principal] = lambda: Principal(
        user_id=user.id,
        full_name=user.full_name,
        roles=("manager",),
        must_change_password=False,
        ip="127.0.0.1",
    )
    return TestClient(app)


def test_api_token_without_platform_access_is_403_with_reason(sso_settings: Settings) -> None:
    user = _active_user(10, platform_access=["crm"])
    resp = _matrix_client(sso_settings, user).post("/api/v1/auth/sso/token")

    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "forbidden"
    assert body["details"]["reason"] == "platform_access_denied"
    assert "token" not in body


def test_api_token_with_platform_access_is_issued(sso_settings: Settings) -> None:
    user = _active_user(10, platform_access=["crm", "erp"])
    resp = _matrix_client(sso_settings, user).post("/api/v1/auth/sso/token")

    assert resp.status_code == 200
    assert _decode_issued(resp.json()["token"])["sub"] == "10"
