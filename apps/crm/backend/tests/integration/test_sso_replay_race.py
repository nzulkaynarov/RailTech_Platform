"""SSO-обмен: параллельный повтор одного токена — один вход, остальные «token already used» (S-15).

Раньше `session.get` → `add` → `flush` для `jti` давал при гонке `IntegrityError` и 500 вместо 401.
Теперь одноразовость держит `INSERT … ON CONFLICT DO NOTHING`.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

import httpx
import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import SsoReplayToken
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration
SSO_SECRET = "integration-sso-secret-for-tests-only"
PARALLEL = 8


def _token(user_id: int, jti: str) -> str:
    now = int(time.time())
    claims = {
        "iss": "erp",
        "aud": "crm",
        "sub": str(user_id),
        "name": "Менеджер",
        "iat": now,
        "exp": now + 60,
        "jti": jti,
    }
    return jwt.encode(claims, SSO_SECRET, algorithm="HS256")


@pytest.fixture
async def http(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    settings = live_settings.model_copy(
        update={"platform_sso_enabled": True, "platform_sso_secret": SecretStr(SSO_SECRET)}
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://crm.test") as client:
            yield client


async def test_parallel_exchange_of_one_token_gives_one_session_and_no_500(
    http: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, _ = await make_user(sessions, "sso-race@railtech.uz", ["manager"])
    jti = str(uuid.uuid4())
    token = _token(manager.id, jti)

    responses = await asyncio.gather(
        *(http.post("/api/v1/auth/sso/exchange", json={"token": token}) for _ in range(PARALLEL))
    )

    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [401] * (PARALLEL - 1), codes
    assert all(
        r.json()["message"] == "token already used" for r in responses if r.status_code == 401
    )
    async with sessions() as session:
        stored = await session.scalar(
            select(func.count()).select_from(SsoReplayToken).where(SsoReplayToken.jti == jti)
        )
    assert stored == 1


async def test_sequential_replay_keeps_the_same_error(
    http: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, _ = await make_user(sessions, "sso-replay@railtech.uz", ["manager"])
    token = _token(manager.id, str(uuid.uuid4()))

    first = await http.post("/api/v1/auth/sso/exchange", json={"token": token})
    second = await http.post("/api/v1/auth/sso/exchange", json={"token": token})

    assert first.status_code == 200
    assert second.status_code == 401
    assert second.json()["message"] == "token already used"
