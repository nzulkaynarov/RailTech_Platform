"""Токен сотрудника для EDS: `POST /api/v1/auth/sso/token` с телом `{"aud": "eds"}` (волна 12, E4).

Норматив — docs/architecture/sso-token.md, «Токен сотрудника для EDS»: тот же JWT HS256 тем же
секретом (первое значение `PLATFORM_SSO_SECRET`), `iss = crm`, `aud = eds`, `exp = iat + 60`,
`jti` — UUID v4, `permissions` — коды `permissions.eds` (справочно); выдача только активному
сотруднику с непустым `permissions.eds`, иначе 403 `eds_access_denied`. Тело без `aud` или
`aud = erp` — токен для ERP, как раньше.
"""

import uuid
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import errors
from app.api.deps import get_container, get_principal
from app.api.v1.auth import router as auth_router
from app.config import Settings
from app.domain.eds_permissions import EDS_PERMISSIONS
from app.domain.errors import ForbiddenError
from app.models.auth import User
from app.models.platform_roles import PlatformRole
from app.security.principal import Principal
from app.services.sso import SsoService
from tests.platform_role_data import make_role
from tests.unit.services.test_sso import (
    SECRET_1,
    SECRET_2,
    _active_user,
    make_session_factory,
)


@pytest.fixture
def sso_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        postgres_host="db.invalid",
        postgres_password="test-password",
        platform_sso_secret=SecretStr(f"{SECRET_1},{SECRET_2}"),
        platform_sso_enabled=True,
        erp_frontend_url="http://erp.localhost",
        jwt_secret=SecretStr("crm-jwt-secret-at-least-32-chars-long"),
    )


ACCOUNTANT = [
    "letters.read",
    "memos.create",
    "payments.confirm",
    "registry.export",
    "registry.read",
]


@pytest.fixture
def roles_of(monkeypatch: pytest.MonkeyPatch) -> dict[int, list[PlatformRole]]:
    """Роли Платформы сотрудников (сессии здесь подставные, без БД)."""
    held: dict[int, list[PlatformRole]] = {}

    async def fake(_: Any, user_id: int) -> list[PlatformRole]:
        return held.get(user_id, [])

    monkeypatch.setattr("app.services.sso.platform_roles_repo.roles_of_user", fake)
    return held


def _service(settings: Settings, user: User) -> SsoService:
    return SsoService(make_session_factory({user.id: user}), settings, SimpleNamespace())  # type: ignore[arg-type]


def _decode(token: str) -> dict[str, Any]:
    return jwt.decode(token, SECRET_1, algorithms=["HS256"], audience="eds", issuer="crm")


@pytest.mark.asyncio
async def test_director_gets_an_eds_token_with_the_document_codes(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    user = _active_user(7)
    roles_of[7] = [make_role("DIRECTOR")]

    token, redirect_url = await _service(sso_settings, user).issue_token(7, aud="eds")

    claims = _decode(token)
    assert set(claims) == {"iss", "aud", "sub", "email", "name", "permissions", "iat", "exp", "jti"}
    assert (claims["iss"], claims["aud"], claims["sub"]) == ("crm", "eds", "7")
    assert (claims["email"], claims["name"]) == ("user7@railtech.uz", "Сотрудник")
    assert claims["exp"] - claims["iat"] == 60
    assert uuid.UUID(claims["jti"]).version == 4
    # журнал шины (`bus.manage`) — раздел `admin: full`, у директора `admin: read` (W13-A2)
    # «Счета и оплаты» у директора — read (D2-4): без подтверждения оплаты
    assert claims["permissions"] == sorted(
        set(EDS_PERMISSIONS) - {"bus.manage", "payments.confirm"}
    )
    assert redirect_url == "", "у EDS нет внешнего маршрута"


@pytest.mark.asyncio
async def test_token_is_signed_with_the_first_secret_only(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    user = _active_user(7)
    roles_of[7] = [make_role("ADMIN")]

    token, _ = await _service(sso_settings, user).issue_token(7, aud="eds")

    assert _decode(token)["permissions"] == ["bus.manage", "memos.create"]
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, SECRET_2, algorithms=["HS256"], audience="eds", issuer="crm")


@pytest.mark.asyncio
async def test_two_roles_give_the_union_of_their_codes(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    user = _active_user(7)
    roles_of[7] = [make_role("MANAGER"), make_role("ACCOUNTANT")]

    token, _ = await _service(sso_settings, user).issue_token(7, aud="eds")

    # MANAGER (`crm.clients: full`) добавляет свой файл в EDS — письмо директору (D1-2b)
    assert _decode(token)["permissions"] == sorted([*ACCOUNTANT, "files.upload"])


@pytest.mark.asyncio
async def test_each_token_has_its_own_jti(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    user = _active_user(7)
    roles_of[7] = [make_role("MANAGER")]
    service = _service(sso_settings, user)

    first, _ = await service.issue_token(7, aud="eds")
    second, _ = await service.issue_token(7, aud="eds")

    assert _decode(first)["jti"] != _decode(second)["jti"]


@pytest.mark.asyncio
async def test_employee_without_eds_codes_is_refused(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    user = _active_user(7)  # ролей Платформы нет -> permissions.eds пуст
    with pytest.raises(ForbiddenError) as refused:
        await _service(sso_settings, user).issue_token(7, aud="eds")
    assert refused.value.details["reason"] == "eds_access_denied"

    roles_of[7] = [
        PlatformRole(id=90, name="Без EDS", access={"crm.leads": "full"}, restricted_fields=[])
    ]
    with pytest.raises(ForbiddenError) as other:
        await _service(sso_settings, user).issue_token(7, aud="eds")
    assert other.value.details["reason"] == "eds_access_denied"


@pytest.mark.asyncio
async def test_inactive_employee_is_refused_even_with_the_director_role(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    user = _active_user(7)
    user.is_active = False
    roles_of[7] = [make_role("DIRECTOR")]

    with pytest.raises(ForbiddenError) as refused:
        await _service(sso_settings, user).issue_token(7, aud="eds")
    assert refused.value.details["reason"] == "eds_access_denied"


@pytest.mark.asyncio
async def test_erp_token_is_unchanged_by_the_eds_branch(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    user = _active_user(7)
    roles_of[7] = [make_role("DIRECTOR")]

    token, redirect_url = await _service(sso_settings, user).issue_token(7)

    claims = jwt.decode(token, SECRET_1, algorithms=["HS256"], audience="erp", issuer="crm")
    assert claims["aud"] == "erp"
    assert "role" in claims
    assert redirect_url == "http://erp.localhost/sso/exchange"
    with pytest.raises(jwt.InvalidAudienceError):
        _decode(token)


@pytest.mark.asyncio
async def test_eds_token_needs_no_erp_access(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    user = _active_user(7, platform_access=["crm"])
    roles_of[7] = [make_role("MANAGER")]

    token, _ = await _service(sso_settings, user).issue_token(7, aud="eds")

    assert _decode(token)["sub"] == "7"


# --- API ---------------------------------------------------------------------------------------


def _client(settings: Settings, user: User) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(auth_router)
    sso = _service(settings, user)
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


def test_api_eds_token_is_issued_for_the_requested_audience(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    user = _active_user(7)
    roles_of[7] = [make_role("ACCOUNTANT")]

    resp = _client(sso_settings, user).post("/api/v1/auth/sso/token", json={"aud": "eds"})

    assert resp.status_code == 200, resp.text
    assert _decode(resp.json()["token"])["permissions"] == ACCOUNTANT


def test_api_eds_token_without_codes_is_403_with_reason(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    resp = _client(sso_settings, _active_user(7)).post(
        "/api/v1/auth/sso/token", json={"aud": "eds"}
    )

    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "forbidden"
    assert body["details"]["reason"] == "eds_access_denied"
    assert "token" not in body


@pytest.mark.parametrize("body", [None, {}, {"aud": "erp"}])
def test_api_without_audience_or_with_erp_issues_the_erp_token(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]], body: dict[str, str] | None
) -> None:
    resp = _client(sso_settings, _active_user(7)).post("/api/v1/auth/sso/token", json=body)

    assert resp.status_code == 200, resp.text
    claims = jwt.decode(
        resp.json()["token"], SECRET_1, algorithms=["HS256"], audience="erp", issuer="crm"
    )
    assert claims["aud"] == "erp"
    assert resp.json()["redirect_url"] == "http://erp.localhost/sso/exchange"


def test_api_without_a_body_issues_the_erp_token(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]]
) -> None:
    resp = _client(sso_settings, _active_user(7)).post("/api/v1/auth/sso/token")

    assert resp.status_code == 200, resp.text
    assert resp.json()["redirect_url"] == "http://erp.localhost/sso/exchange"


@pytest.mark.parametrize("aud", ["crm", "ERP", "", "eds-api", 7])
def test_api_unknown_audience_is_422(
    sso_settings: Settings, roles_of: dict[int, list[PlatformRole]], aud: object
) -> None:
    resp = _client(sso_settings, _active_user(7)).post("/api/v1/auth/sso/token", json={"aud": aud})

    assert resp.status_code == 422
    assert "token" not in resp.json()
